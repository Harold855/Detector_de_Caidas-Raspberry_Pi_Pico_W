# ============================================================
#  DETECTOR DE CAÍDAS v22 — con WiFi + Telegram
#  MicroPython para Raspberry Pi Pico W (o ESP32)
# ============================================================
#
#  FLUJO GENERAL DEL PROGRAMA (qué hace, paso a paso):
#
#  1. Al arrancar: se conecta al WiFi, despierta el sensor MPU6050
#     y avisa por Telegram que el dispositivo ya está listo.
#
#  2. Bucle principal (corre todo el tiempo, varias veces por segundo):
#       a) Cada pocos segundos revisa que el WiFi siga conectado;
#          si se cayó, intenta reconectar solo.
#       b) Lee el sensor (aceleración total + giro total + inclinación).
#       c) PASO 1 - ¿Hubo un giro brusco? (evento_decisivo)
#          Si NO -> sigue leyendo normal, no pasa nada.
#          Si SÍ -> pasa al paso 2.
#       d) PASO 2 - Verificación de postura e inmovilidad: observa
#          unos segundos más para confirmar si de verdad quedó
#          caída (postura anormal + quieta) o si fue un movimiento
#          brusco normal (salto, girarse rápido, etc.).
#       e) Si se confirma -> pitido corto + mensaje a Telegram +
#          5 segundos sonando fuerte y seguido para que la persona
#          cancele con 1 toque.
#       f) Si nadie cancela -> EMERGENCIA: pitido tipo sirena +
#          mensaje urgente a Telegram, hasta que alguien haga la
#          secuencia de toques para silenciar o pasen 5 minutos.
#
#  En resumen: SENSOR -> ¿GIRO BRUSCO? -> ¿POSTURA + QUIETUD? ->
#  AVISO CON 5s PARA CANCELAR (pitido continuo) -> EMERGENCIA SI NADIE RESPONDE
#
#  MENSAJES QUE SE ENVÍAN A TELEGRAM:
#
#  1. Al detectar movimiento brusco:
#     "POSIBLE CAIDA — [nombre] podria haberse caido.
#      Esperando confirmacion... (5 segundos)"
#
#  2. Si la persona presiona el boton entonces esta bien:
#     "FALSA ALARMA — [nombre] cancelo la alerta. Esta bien."
#
#  3. Si nadie la presiona, presunta caida real:
#     "CAIDA CONFIRMADA — [nombre] necesita ayuda. Actuen ya."
#
#  4. Cuando alguien silencia la alarma en el lugar:
#     "Alarma silenciada en el dispositivo."
#
# ============================================================

from machine import Pin, I2C
import machine
import network
import urequests   # Librería HTTP incluida en MicroPython
import time
import math
import struct

# ======================
# ZONA DE CONFIGURACIÓN  
# ======================
# --- Datos de la persona (aparecen en los mensajes de Telegram) ---
NOMBRE_PERSONA = "Karen"   # Nombre que podrán ver los familiares

# --- La red WiFi ---
WIFI_NOMBRE   = "Galaxy A52s"   # El nombre de tu red (SSID)
WIFI_CLAVE    = "Rivera22"      # La contraseña de tu WiFi

# --- El bot de Telegram (ver instrucciones para configurar el bot) ---
TELEGRAM_TOKEN   = "8929869831:AAEx3ck3OAIMjsW67cCKW-MN5bR33Ubgh7o"   # Token de tu bot
TELEGRAM_CHAT_ID = "-1004371751964"        # ID del grupo familiar

# --- Modo de prueba ---
# Si está en True, se salta la verificación de postura/inmovilidad y
# confirma la caída apenas detecta el giro brusco. Útil SOLO para
# probar que el giro se detecta bien (ej. levantar y soltar el
# sensor). Para uso real con la persona, debe quedar en False, porque
# si no, cualquier giro brusco sin caída real también activaría todo.
MODO_PRUEBA = False

# --- Umbrales del detector ---
# La aceleración es solo un "habilitador" (umbral bajo, casi siempre se
# cumple durante cualquier movimiento brusco). El GIRO es el factor
# decisivo: un salto casi no gira, una caída real sí.
UMBRAL_CAIDA_MIN     = 1.1   # g-force mínimo para considerar "hubo movimiento brusco"
UMBRAL_GIRO_DPS      = 72    # Giro brusco decisivo, en grados por segundo
UMBRAL_INCLINACION   = 50     # Inclinación anormal en grados (ya no está de pie)

# --- Confirmación posterior (evita que un salto, sentarse o echarse de
# forma normal active la alarma) ---
# Sentarse o acostarse despacio NO genera un giro mayor a UMBRAL_GIRO_DPS,
# así que ni siquiera entra a esta verificación (queda filtrado en el
# PASO 1). Solo si el movimiento fue brusco (alto giro) entra aquí, y
# durante estos segundos el sistema sigue leyendo y "se actualiza":
# si la persona se queda quieta en postura anormal, confirma caída;
# si vuelve a moverse o su postura es normal, se descarta.
TIEMPO_VERIFICACION   = 2.5   # segundos para revisar postura + inmovilidad tras el giro
UMBRAL_QUIETUD        = 0.70  # variación máxima de aceleración para considerar "inmóvil" (g)

# Porcentaje del TIEMPO_VERIFICACION que se descarta al principio (el
# "rebote" justo después del golpe) antes de empezar a medir si la
# persona está realmente quieta. Va de 0.0 (no descarta nada) a 0.9
# (descarta casi todo el tiempo).
# Ejemplo con TIEMPO_VERIFICACION = 2.0s:
#   PORCENTAJE_ASENTAMIENTO = 0.3  -> descarta 0.6s, mide quietud en 1.4s
#   PORCENTAJE_ASENTAMIENTO = 0.1  -> descarta 0.2s, mide quietud en 1.8s
#     (MÁS FÁCIL que se confirme "quieta": menos tiempo descartado,
#      pero más riesgo de que el rebote del golpe arruine la medición)
#   PORCENTAJE_ASENTAMIENTO = 0.5  -> descarta 1.0s, mide quietud en 1.0s
#     (MÁS DIFÍCIL que se confirme "quieta": le da más margen al cuerpo
#      para asentarse antes de medir, pero queda menos tiempo de medición)
PORCENTAJE_ASENTAMIENTO = 0.20

TIEMPO_CANCELACION   = 5    # segundos para cancelar con 1 toque
TIEMPO_ALARMA_MAXIMO = 300   # segundos antes de apagarse sola (5 min)

# --- WiFi: cuántas veces intenta conectar antes de rendirse ---
# Ejemplo: si cada intento dura 1 segundo...
#   INTENTOS_WIFI_INICIAL = 20  -> espera hasta 20s al arrancar (MÁS
#     tiempo para que la red esté lista, pero tarda más en encender)
#   INTENTOS_WIFI_INICIAL = 10  -> espera hasta 10s al arrancar (MÁS
#     rápido para encender, pero si la red tarda en estar lista, se
#     rinde antes y arranca sin Telegram)
INTENTOS_WIFI_INICIAL     = 50   # intentos al arrancar el dispositivo
INTENTOS_WIFI_RECONEXION  = 20   # intentos cuando se reconecta tras una caída de WiFi

# --- Para silenciar la alarma de emergencia ---
TOQUES_PARA_SILENCIAR = 2    # toques necesarios
VENTANA_TOQUES        = 2.0  # segundos en los que deben ocurrir

# --- Tiempos del pitido ---
PITIDO_ON  = 0.15   # más breve y rápido que antes -> suena más urgente
PITIDO_OFF = 0.15
PITIDO_ALERTA_DURACION = 0.15   # pitido corto al detectar, antes de la ventana de cancelación
PAUSA_ENTRE_GRUPOS = 0.70   # pausa entre cada "doble pitido" de emergencia (tipo sirena)
                            # también es la ventana en la que se escuchan los toques
                            # para silenciar — no la bajes demasiado o será muy difícil
                            # completar los 4 toques a tiempo

# --- Pitido durante los 5s de cancelación (TIEMPO_CANCELACION) ---
# Antes solo sonaba un pitido corto al detectar la caída y luego
# quedaba en silencio durante toda la ventana de cancelación. Ahora
# suena fuerte y seguido durante TODOS esos segundos, para que la
# persona caída (o alguien cerca) lo escuche y sepa que debe tocar
# el botón si está bien.
PITIDO_ON_CANCELACION  = 0.15   # duración de cada pitido durante la cancelación
PITIDO_OFF_CANCELACION = 0.15   # silencio entre cada pitido durante la cancelación

# --- Truco anti-apagado del power bank ---
# Muchos power banks se apagan solos cuando detectan que el consumo
# de corriente es muy bajo (la Pico en reposo casi no consume nada,
# y el power bank "cree" que no hay nada conectado y se apaga para
# ahorrar batería). Esto es un comportamiento del HARDWARE del power
# bank, no se puede arreglar 100% por software. El truco que sí
# ayuda: generar cada cierto tiempo un pequeño "pico" de consumo
# extra (un pulso muy breve y casi inaudible del buzzer) para que el
# power bank detecte actividad y no se apague. No es infalible —
# depende de la sensibilidad de cada modelo de power bank — pero en
# la mayoría de los casos evita el apagado automático. Si tu power
# bank se sigue apagando, no hay forma de garantizarlo solo con
# código; la alternativa sería un power bank con "modo trickle/baja
# carga" o uno pensado para cámaras/cargadores de bajo consumo.
INTERVALO_ANTIAPAGADO = 3    # segundos entre cada pulso anti-apagado
PULSO_ANTIAPAGADO     = 0.1  # duración del pulso (muy breve)

# =======================================
# INSTRUCCIONES PARA CONFIGURAR TELEGRAM 
# =======================================
#
#  PASO 1 — Crear el bot:
#    a) Abre Telegram y busca "@BotFather"
#    b) Escribe /newbot
#    c) Ponle un nombre, ej: "Alerta Abuela María"
#    d) BotFather te dará un TOKEN como: 123456789:ABCdef...
#    e) Cópialo en TELEGRAM_TOKEN arriba
#
#  PASO 2 — Crear el grupo familiar:
#    a) Crea un grupo en Telegram con los familiares
#    b) Añade tu bot al grupo
#    c) Escríbele al bot desde el grupo: /start
#    d) Entra a este link en el navegador (cambia TOKEN por el tuyo): https://api.telegram.org/botTOKEN/getUpdates
#    e) Busca "chat":{"id": y copia ese número (empieza con -)
#    f) Pégalo en TELEGRAM_CHAT_ID arriba

# ===========================
# CONFIGURACIÓN DEL HARDWARE
# ===========================
# Esto se hace dentro de una función (en vez de directo aquí abajo)
# para que, si el sensor MPU6050 falla al arrancar (cable suelto,
# sensor no detectado, etc.), el error quede atrapado por el bucle
# exterior que nunca muere, en vez de detener el programa por completo.

MPU = 0x68

def inicializar_hardware():
    global buzzer_pin, boton, i2c, wifi

    buzzer_pin = Pin(16, Pin.OUT)
    buzzer_pin.value(1)   # 1 = APAGADO de inmediato. Importante: este buzzer
                           # es de tipo "activo, lógica invertida" (active-low):
                           # enciende con 0 y apaga con 1. Si se deja flotando o
                           # en 0 por error, suena sin parar — por eso se fija
                           # en 1 desde el principio, antes de cualquier otra cosa.
    boton  = Pin(14, Pin.IN, Pin.PULL_UP)

    i2c = I2C(0, scl=Pin(5), sda=Pin(4), freq=400000)
    i2c.writeto_mem(MPU, 0x6B, b'\x00')   # Despierta el acelerómetro

    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)

# ========================
# FUNCIONES DE BUZZER
# ========================
# Este buzzer es ACTIVO: trae su propio oscilador interno, así que no
# necesita que el código genere ninguna frecuencia (a diferencia de un
# buzzer pasivo). Solo necesita un encendido/apagado simple, pero con
# lógica invertida: 0 = encendido, 1 = apagado.

def buzzer_on(frecuencia=None):
    # 'frecuencia' se deja como parámetro solo para no romper las
    # llamadas existentes en el resto del código; este buzzer la ignora.
    buzzer_pin.value(0)   # 0 = encendido (lógica invertida)

def buzzer_off():
    buzzer_pin.value(1)   # 1 = apagado (lógica invertida)

# FUNCIÓN: CONECTAR AL WIFI


TIEMPO_ENTRE_REVISIONES_WIFI = 2   # segundos entre cada revisión de la conexión

def conectar_wifi():
    """
    Conecta al WiFi y espera hasta que haya conexión.
    Muestra un punto cada segundo mientras espera.
    Si no conecta en 20 segundos, continúa sin internet
    (el detector sigue funcionando, solo sin Telegram).
    """
    wifi.connect(WIFI_NOMBRE, WIFI_CLAVE)

    print(f"Conectando a WiFi '{WIFI_NOMBRE}'", end="")
    intentos = 0
    while not wifi.isconnected() and intentos < INTENTOS_WIFI_INICIAL:
        print(".", end="")
        time.sleep(1)
        intentos += 1

    if wifi.isconnected():
        print(f"\n WiFi conectado - IP: {wifi.ifconfig()[0]}\n")
        return True
    else:
        print("\n No se pudo conectar al WiFi. Sin alertas Telegram.\n")
        return False

def verificar_wifi(avisar=True):
    """
    Revisa si el WiFi sigue conectado. Si se cayó, intenta reconectar
    de inmediato (rápido, sin esperar los 20 segundos completos) y
    muestra en consola si lo logró o no, igual que con las caídas.
    Devuelve True/False según el estado actual de la conexión.

    'avisar' controla si esta función manda ella misma el mensaje de
    "reconectado" por Telegram. Se pone en False cuando quien la llama
    (como el bucle de emergencia) ya se encarga de avisar por su cuenta,
    para no mandar el mismo aviso dos veces.
    """
    if wifi.isconnected():
        return True

    print("\n>>> WiFi desconectado. Intentando reconectar... <<<")
    wifi.disconnect()
    wifi.connect(WIFI_NOMBRE, WIFI_CLAVE)

    intentos = 0
    while not wifi.isconnected() and intentos < INTENTOS_WIFI_RECONEXION:
        print(".", end="")
        time.sleep(1)
        intentos += 1

    if wifi.isconnected():
        print(f"\n>>> WiFi reconectado - IP: {wifi.ifconfig()[0]} <<<\n")
        if avisar:
            enviar_telegram(
                f"Dispositivo de {NOMBRE_PERSONA} reconectado al WiFi.\n"
                f"El monitoreo de Telegram esta activo de nuevo."
            )
        return True
    else:
        print("\n>>> Reconexión fallida. Se reintentará pronto. <<<\n")
        return False

# =======================================
# FUNCIÓN: ENVIAR MENSAJE A TELEGRAM
# =======================================

def enviar_telegram(mensaje, intentos=2):
    """
    Envía un mensaje al grupo de Telegram usando GET con URL.
    Es el mismo método que funciona en el navegador.

    Reintenta una vez más si falla (con una pequeña pausa), porque
    justo después de reconectar el WiFi, el router ya da conexión
    pero a veces el internet real tarda uno o dos segundos más en
    estar listo, y el primer intento puede fallar aunque la red ya
    se vea como "conectada". Si todos los intentos fallan, imprime
    el error y continúa sin detener el detector.
    """
    for intento in range(1, intentos + 1):
        try:
            # Limpiamos caracteres especiales que rompen la URL
            msg = mensaje
            for orig, repl in [(" ", "%20"), ("\n", "%0A"), ("á","a"), ("é","e"),
                               ("í","i"), ("ó","o"), ("ú","u"), ("ñ","n"),
                               ("¡",""), ("¿",""), ("<b>",""), ("</b>","")]:
                msg = msg.replace(orig, repl)

            url = (f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                   f"?chat_id={TELEGRAM_CHAT_ID}&text={msg}")

            respuesta = urequests.get(url, timeout=10)
            respuesta.close()
            print(f"  [Telegram] Enviado OK")
            return True
        except Exception as e:
            print(f"  [Telegram] Error (intento {intento}/{intentos}): {e}")
            if intento < intentos:
                time.sleep(1.5)   # le damos un respiro a la red antes de reintentar

    # Todos los intentos fallaron — el detector sigue funcionando igual
    return False

# FUNCIÓN: LEER EL ACELERÓMETRO MPU-6050

def leer_mpu6050():
    """
    Lectura del acelerómetro y giroscopio del MPU6050.
    
    Devuelve:
    -> aceleracion_total: magnitud de aceleración en g
    -> giro_total: magnitud del giro en grados/segundo
    -> roll: inclinación lateral
    -> pitch: inclinación frontal
    -> gx, gy, gz: giroscopio por eje
    """
    datos = i2c.readfrom_mem(MPU, 0x3B, 14)
    
    # Acelerómetro
    ax = struct.unpack(">h", datos[0:2])[0] / 16384.0
    ay = struct.unpack(">h", datos[2:4])[0] / 16384.0
    az = struct.unpack(">h", datos[4:6])[0] / 16384.0
    
    # Giroscopio
    gx = struct.unpack(">h", datos[8:10])[0] / 131.0
    gy = struct.unpack(">h", datos[10:12])[0] / 131.0
    gz = struct.unpack(">h", datos[12:14])[0] / 131.0
    
    # Magnitud total del acelerómetro
    aceleracion_total = math.sqrt(ax * ax + ay * ay + az * az)

    # Magnitud total del giroscopio
    giro_total = math.sqrt(gx * gx + gy * gy + gz * gz)
    
    # Inclinación aproximada usando acelerómetro
    roll = math.degrees(math.atan2(ay, az))
    pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
    
    return aceleracion_total, giro_total, roll, pitch, gx, gy, gz

# =========================================================
# FUNCIÓN: ESPERAR 1 SOLO TOQUE (para cancelar la alerta)
# =========================================================

def esperar_un_toque(segundos):
    """
    Espera hasta 'segundos' a que se presione el botón UNA VEZ.
    Devuelve True si se presionó, False si se acabó el tiempo.

    Se usa en la ventana de 15s porque la anciana está asustada
    y no puede recordar secuencias. Un toque basta para decir
    "estoy bien".
    """
    inicio        = time.time()
    boton_soltado = True

    while (time.time() - inicio) < segundos:
        presionado = (boton.value() == 0)   # Pull-up: 0 = presionado

        if presionado and boton_soltado:
            return True

        boton_soltado = not presionado
        time.sleep(0.02)

    return False

# FUNCIÓN: ESPERAR 1 TOQUE, PERO PITANDO FUERTE Y SEGUIDO MIENTRAS TANTO

def esperar_toque_con_pitido(segundos, pitido_on=PITIDO_ON_CANCELACION,
                              pitido_off=PITIDO_OFF_CANCELACION):
    """
    Igual que esperar_un_toque(), pero además hace sonar el buzzer en
    pitidos repetidos durante TODA la espera (no solo al principio),
    para que la alarma sea audible y continua durante la ventana de
    cancelación. Sigue revisando el botón a la vez que pita, así que
    el toque se detecta de inmediato sin tener que esperar a que
    termine un ciclo de pitido.

    Devuelve True si se presionó el botón (y deja el buzzer apagado),
    False si se acabó el tiempo sin que nadie tocara.
    """
    inicio          = time.time()
    boton_soltado   = True
    pitido_prendido = False
    ultimo_cambio   = time.time()

    while (time.time() - inicio) < segundos:
        presionado = (boton.value() == 0)   # Pull-up: 0 = presionado

        if presionado and boton_soltado:
            buzzer_off()
            return True

        boton_soltado = not presionado

        # Alternamos encendido/apagado del buzzer sin bloquear la
        # revisión del botón (revisamos cada pocos milisegundos)
        ahora = time.time()
        duracion_fase = pitido_on if pitido_prendido else pitido_off
        if (ahora - ultimo_cambio) >= duracion_fase:
            pitido_prendido = not pitido_prendido
            if pitido_prendido:
                buzzer_on()
            else:
                buzzer_off()
            ultimo_cambio = ahora

        time.sleep(0.01)

    buzzer_off()
    return False

def esperar_secuencia_toques(segundos_totales):
    """
    Busca TOQUES_PARA_SILENCIAR toques dentro de VENTANA_TOQUES segundos.
    Devuelve True si se completa la secuencia, False si no.

    Se usa en la alarma de emergencia para que no se apague
    por accidente. Solo alguien consciente puede hacer 4 toques
    rápidos. La anciana caída no podría hacerlo.
    """
    conteo              = 0
    tiempo_primer_toque = 0
    boton_soltado       = True
    inicio              = time.time()

    while (time.time() - inicio) < segundos_totales:
        presionado = (boton.value() == 0)

        if presionado and boton_soltado:
            ahora = time.time()

            if conteo == 0:
                # Primer toque: empezamos a contar la ventana
                conteo              = 1
                tiempo_primer_toque = ahora
                print(f"  Toque 1/{TOQUES_PARA_SILENCIAR}")

            elif (ahora - tiempo_primer_toque) <= VENTANA_TOQUES:
                # Toque dentro de la ventana: sumamos
                conteo += 1
                print(f"  Toque {conteo}/{TOQUES_PARA_SILENCIAR}")
                if conteo >= TOQUES_PARA_SILENCIAR:
                    return True   # ¡Secuencia completa!

            else:
                # La ventana expiró: reiniciamos desde este toque
                conteo              = 1
                tiempo_primer_toque = ahora
                print(f"  Toque 1/{TOQUES_PARA_SILENCIAR} (reiniciado)")

        boton_soltado = not presionado
        time.sleep(0.02)

    return False

# INICIO DEL PROGRAMA

def ejecutar_programa():
    """
    Contiene TODO el programa: conexión WiFi, mensaje inicial y el
    bucle principal. Se ejecuta dentro de un bucle exterior (más
    abajo) que la atrapa si algo falla de forma grave -- así el
    dispositivo nunca se queda apagado/muerto mientras tenga batería.
    """
    inicializar_hardware()   # prepara buzzer, botón, sensor MPU6050 y WiFi


    print(f"  DETECTOR DE CAIDAS v22")
    print(f"  Persona: {NOMBRE_PERSONA}")
    print(f"  1 toque       -> cancela alerta")
    print(f"  {TOQUES_PARA_SILENCIAR} toques en {VENTANA_TOQUES}s -> silencia emergencia")
    
    wifi_ok = conectar_wifi()   # Intentamos conectar al WiFi al arrancar

    if wifi_ok:
        # Mensaje de prueba para confirmar que Telegram funciona
        enviar_telegram(f"Dispositivo de {NOMBRE_PERSONA} conectado y listo.")

    ultima_revision_wifi = time.time()
    ultimo_pulso_antiapagado = time.time()


    # BUCLE PRINCIPAL


    while True:
        try:
            # --------------------------------------------------------
            # Revisamos el WiFi cada pocos segundos (no en cada vuelta del
            # bucle, para no atrasar la lectura de los sensores). Si se
            # cayó, intenta reconectar y avisa en consola si lo logró o no.
            # --------------------------------------------------------
            if (time.time() - ultima_revision_wifi) > TIEMPO_ENTRE_REVISIONES_WIFI:
                verificar_wifi()
                ultima_revision_wifi = time.time()

            # --------------------------------------------------------
            # Truco anti-apagado del power bank: cada cierto tiempo
            # generamos un pequeño pulso de consumo extra para que el
            # power bank no piense que no hay nada conectado.
            # --------------------------------------------------------
            if (time.time() - ultimo_pulso_antiapagado) > INTERVALO_ANTIAPAGADO:
                buzzer_on()
                time.sleep(PULSO_ANTIAPAGADO)
                buzzer_off()
                ultimo_pulso_antiapagado = time.time()

            accel, giro, roll, pitch, gx, gy, gz = leer_mpu6050()

            print(
                "Aceleración:", round(accel, 2), "g",
                "| Giro total:", round(giro, 2), "°/s",
                "| Gx:", round(gx, 2),
                "| Gy:", round(gy, 2),
                "| Gz:", round(gz, 2),
                "| Roll:", round(roll, 2), "°",
                "| Pitch:", round(pitch, 2), "°"
            )

            # --------------------------------------------------------
            # PASO 1: ¿Hubo un evento decisivo de caída?
            #
            # La aceleración es solo el "habilitador" (umbral bajo, casi
            # siempre se cumple con cualquier movimiento brusco). Lo que
            # realmente decide es el GIRO: un salto casi no gira, una
            # caída real sí, porque el cuerpo pierde el control.
            # --------------------------------------------------------
            inclinacion = max(abs(roll), abs(pitch))
            evento_decisivo = (accel > UMBRAL_CAIDA_MIN and giro > UMBRAL_GIRO_DPS)

            if evento_decisivo:
                print("\n>>> Giro brusco detectado - verificando si es una caída real... <<<")
                print("Aceleración:", round(accel, 2), "g | Giro:", round(giro, 2), "°/s")

                if MODO_PRUEBA:
                    print(">>> MODO_PRUEBA activo: se confirma de una vez, sin revisar postura <<<\n")
                    posible_caida = True

                else:
                    # ----------------------------------------------------------------
                    # PASO 2: VERIFICACIÓN DE POSTURA + INMOVILIDAD
                    # Un salto vuelve a la postura normal y sigue en movimiento casi
                    # de inmediato. Una caída real deja a la persona en una postura
                    # anormal (no de pie) y quieta varios segundos. Solo si se
                    # cumplen AMBAS cosas pasamos a la alerta de verdad.
                    # ----------------------------------------------------------------
                    lecturas_verificacion = []
                    inicio_verif = time.time()
                    tiempo_asentamiento = TIEMPO_VERIFICACION * PORCENTAJE_ASENTAMIENTO   # descarta el rebote del golpe

                    while (time.time() - inicio_verif) < TIEMPO_VERIFICACION:
                        a_v, g_v, roll_v, pitch_v, _, _, _ = leer_mpu6050()
                        transcurrido = time.time() - inicio_verif

                        # Solo guardamos lecturas DESPUÉS del asentamiento, para
                        # que un rebote inicial del golpe no arruine el cálculo
                        # de quietud con un solo dato suelto
                        if transcurrido >= tiempo_asentamiento:
                            lecturas_verificacion.append(a_v)

                        etiqueta = "asentando" if transcurrido < tiempo_asentamiento else "midiendo quietud"
                        print(f"    [{etiqueta}] accel={round(a_v,2)}g  "
                              f"roll={round(roll_v,1)}°  pitch={round(pitch_v,1)}°")
                        time.sleep(0.1)

                    inclinacion_final = max(abs(roll_v), abs(pitch_v))
                    if len(lecturas_verificacion) >= 2:
                        variacion = max(lecturas_verificacion) - min(lecturas_verificacion)
                    else:
                        # Si TIEMPO_VERIFICACION es muy corto y no alcanzó a
                        # tomar lecturas tras el asentamiento, no se puede medir
                        # quietud de forma confiable
                        variacion = 999
                    quieta = variacion < UMBRAL_QUIETUD
                    postura_anormal = inclinacion_final > UMBRAL_INCLINACION

                    print(f"  Inclinación final: {round(inclinacion_final,1)}° | "
                          f"Variación de accel: {round(variacion,2)}g | "
                          f"Quieta: {quieta} | Postura anormal: {postura_anormal}")

                    posible_caida = quieta and postura_anormal

                    if not posible_caida:
                        print(">>> Descartado: parece un movimiento brusco normal (salto, giro rápido, etc.) <<<\n")

            else:
                posible_caida = False

            if posible_caida:
                print("\n>>> ¡CAÍDA CONFIRMADA POR SECUENCIA DE SENSORES! <<<")
                print("Motivo: giro brusco + postura anormal + inmovilidad posterior")

                buzzer_on()
                time.sleep(PITIDO_ALERTA_DURACION)
                buzzer_off()   # pitido corto en vez de tono continuo

                # Enviamos PRIMER MENSAJE: posible caída, aún sin confirmar
                enviar_telegram(
                    f"POSIBLE CAIDA - {NOMBRE_PERSONA}\n"
                    f"Podria haberse caido. Esperando confirmacion...\n"
                    f"({TIEMPO_CANCELACION} segundos para cancelar)"
                )

                # ------------------------------------------------------------------
                # PASO 2: VENTANA DE CANCELACIÓN (TIEMPO_CANCELACION segundos)
                # El buzzer suena fuerte y seguido durante TODA la ventana (no
                # solo al inicio), para que la persona caída o alguien cerca lo
                # escuche. 1 solo toque = la persona está bien, falsa alarma.
                # ------------------------------------------------------------------
                cancelada          = False
                inicio_cancelacion = time.time()

                while (time.time() - inicio_cancelacion) < TIEMPO_CANCELACION:
                    restante = TIEMPO_CANCELACION - int(time.time() - inicio_cancelacion)
                    print(f"  Presiona 1 vez para cancelar: {restante}s")

                    if esperar_toque_con_pitido(2.0):
                        print("\n>>> ALERTA CANCELADA — Persona estable <<<\n")
                        buzzer_off()
                        cancelada = True

                        # Enviamos SEGUNDO MENSAJE: falsa alarma, tranquilos
                        enviar_telegram(
                            f"FALSA ALARMA - {NOMBRE_PERSONA}\n"
                            f"Cancelo la alerta ella misma. Esta bien."
                        )
                        time.sleep(1)
                        break

                # --------------------------------------------------------
                # PASO 3: EMERGENCIA CONFIRMADA
                # Nadie presionó en 15s → asumimos caída real
                # Pitido intermitente + mensaje urgente a Telegram
                # Para silenciar: TOQUES_PARA_SILENCIAR toques en VENTANA_TOQUES segundos
                # --------------------------------------------------------
                if not cancelada:
                    buzzer_off()
                    print("\n***** ¡EMERGENCIA CONFIRMADA! *****")
                    print(f"  Da {TOQUES_PARA_SILENCIAR} toques en {VENTANA_TOQUES}s para silenciar.")
                    print(f"  La alarma se apaga sola en {TIEMPO_ALARMA_MAXIMO}s.")

                    # Enviamos TERCER MENSAJE: emergencia real, necesita ayuda
                    enviar_telegram(
                        f"CAIDA CONFIRMADA - {NOMBRE_PERSONA}\n"
                        f"No respondio en {TIEMPO_CANCELACION} segundos.\n"
                        f"Vayan a ayudarla de inmediato.\n"
                        f"La alarma sonara hasta que alguien llegue."
                    )

                    inicio_alarma = time.time()
                    silenciada    = False

                    # --------------------------------------------------------
                    # Seguimiento del WiFi DENTRO de la emergencia (hasta 5 min)
                    #
                    # wifi_conectado_antes guarda si estaba conectado en la
                    # vuelta anterior del bucle. En CADA vuelta (no solo cada
                    # 30s) comparamos contra el estado actual -- así, en
                    # cuanto pase de "desconectado" a "conectado" (sea porque
                    # lo reconectamos nosotros aquí abajo, o porque se
                    # reconectó solo en el medio), lo detectamos de inmediato
                    # y mandamos los dos avisos. Antes solo se revisaba cada
                    # 30s, así que si se reconectaba ANTES de que tocara
                    # revisar, el aviso se perdía porque ya lo encontraba
                    # conectado y no se daba cuenta de que hubo una caída.
                    # --------------------------------------------------------
                    wifi_conectado_antes = wifi.isconnected()
                    ultimo_intento_reconexion_alarma = time.time()

                    while (time.time() - inicio_alarma) < TIEMPO_ALARMA_MAXIMO:

                        wifi_conectado_ahora = wifi.isconnected()

                        # Si justo ahora se reconectó (antes no, ahora sí)
                        if wifi_conectado_ahora and not wifi_conectado_antes:
                            enviar_telegram(
                                f"Dispositivo de {NOMBRE_PERSONA} reconectado al WiFi.\n"
                                f"El monitoreo de Telegram esta activo de nuevo."
                            )
                            enviar_telegram(
                                f"CAIDA CONFIRMADA - {NOMBRE_PERSONA}\n"
                                f"La alarma sigue sonando, no respondio a tiempo.\n"
                                f"Vayan a ayudarla de inmediato si aun no han llegado."
                            )

                        # Si sigue desconectado, cada 30s intentamos reconectar de forma activa (verificar_wifi con avisar=False)
                        # Porque el aviso ya lo mandamos arriba apenas se detecta la reconexión, para no duplicar mensajes)

                        elif not wifi_conectado_ahora and (time.time() - ultimo_intento_reconexion_alarma) > 30:
                            verificar_wifi(avisar=False)
                            ultimo_intento_reconexion_alarma = time.time()

                        wifi_conectado_antes = wifi.isconnected()

                        # Patrón de EMERGENCIA tipo sirena: dos pitidos rápidos seguidos y una pausa corta, estose repite
                        buzzer_on()
                        time.sleep(PITIDO_ON)
                        buzzer_off()
                        time.sleep(PITIDO_OFF)

                        buzzer_on()
                        time.sleep(PITIDO_ON)
                        buzzer_off()

                        # Revisa si alguien hace la secuencia de toques durante la pausa entre grupos de pitidos
                        if esperar_secuencia_toques(PAUSA_ENTRE_GRUPOS):
                            silenciada = True
                            print("\n>>> SECUENCIA CORRECTA — Alarma silenciada <<<\n")
                            buzzer_off()

                            # Enviamos CUARTO MENSAJE: alguien llegó y silenció
                            enviar_telegram(
                                f"Alarma silenciada - {NOMBRE_PERSONA}\n"
                                f"Alguien esta con ella en el lugar."
                            )
                            break

                    if not silenciada:
                        # Se acabó el tiempo máximo
                        print(f"\n>>> Tiempo máximo ({TIEMPO_ALARMA_MAXIMO}s). Alarma apagada. <<<\n")
                        buzzer_off()
                        enviar_telegram(
                            f"Alarma apagada automaticamente - {NOMBRE_PERSONA}\n"
                            f"Se alcanzo el tiempo maximo ({TIEMPO_ALARMA_MAXIMO}s).\n"
                            f"Verifiquen su estado."
                        )

                    time.sleep(1)

            time.sleep(0.2)   # Leemos la aceleración 5 veces por segundo

        except Exception as e:
            print("Error:", e)
            buzzer_off()
            time.sleep(2)

# ==========================================================
# BUCLE EXTERIOR — EL PROGRAMA NUNCA MUERE
# ==========================================================
# Si ocurre un error grave que detiene el programa principal, este bucle reinicia automáticamente la Raspberry Pi Pico W.
# Así, el detector vuelve a iniciar desde cero y continúa funcionando mientras tenga batería.
while True:
    try:
        ejecutar_programa()
    except Exception as e:
        print("\n***** ERROR GRAVE — el programa se va a reiniciar solo *****")
        print("Detalle del error:", e)
        try:
            buzzer_off()   # por seguridad, que no quede sonando
        except Exception:
            pass
        time.sleep(3)
        machine.reset()   # reinicio completo de la Pico, como un apagar/prender


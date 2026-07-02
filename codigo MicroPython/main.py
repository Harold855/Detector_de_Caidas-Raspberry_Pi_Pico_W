# ============================================================
#  DETECTOR DE CAÍDAS v22 — con WiFi + Telegram
#  MicroPython para Raspberry Pi Pico W (o ESP32)
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
NOMBRE_PERSONA = "COLOCA EL NOBRE DEL FAMILIAR MAYOR"   # Nombre que podrán ver los familiares

WIFI_NOMBRE = "COLOCA AQUI EL NOMBRE DE TU WIFI" #Nombre de red SSID
WIFI_CLAVE = "COLOCA AQUI LA CLAVE DE TU WIFI"

# --- El bot de Telegram (ver instrucciones para configurar el bot) ---
TELEGRAM_TOKEN = "COLOCA AQUI EL TOKEN DE TU BOT"
TELEGRAM_CHAT_ID = "COLOCA AQUI EL ID DEL CHAT"

# --- Modo de prueba ---
MODO_PRUEBA = False # True: confirma la caida al detectar giro brusco. Uso solo para pruebas

# --- Umbrales del detector ---
UMBRAL_CAIDA_MIN     = 1.1   # Movimiento minimo en g
UMBRAL_GIRO_DPS      = 72    # Giro brusco en grados/segundo
UMBRAL_INCLINACION   = 50    # Postura anormal en grados

# --- Confirmación posterior (evita que un salto, sentarse o echarse de forma normal active la alarma) ---

TIEMPO_VERIFICACION   = 2.5   # segundos para revisar postura + inmovilidad tras el giro
UMBRAL_QUIETUD        = 0.70  # variación máxima de aceleración para considerar "inmóvil" (g)

# Porcentaje del TIEMPO_VERIFICACION que se descarta al principio (el "rebote" justo después del golpe) 
PORCENTAJE_ASENTAMIENTO = 0.20

TIEMPO_CANCELACION   = 5    # segundos para cancelar con 1 toque
TIEMPO_ALARMA_MAXIMO = 300   # segundos antes de apagarse sola (5 min)

# --- WiFi: cuántas veces intenta conectar antes de rendirse ---
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

# --- Pitido durante los 5s de cancelación (TIEMPO_CANCELACION) ---
PITIDO_ON_CANCELACION  = 0.15   # duración de cada pitido durante la cancelación
PITIDO_OFF_CANCELACION = 0.15   # silencio entre cada pitido durante la cancelación

# --- Truco anti-apagado del power bank ---
INTERVALO_ANTIAPAGADO = 3    # segundos entre cada pulso anti-apagado
PULSO_ANTIAPAGADO     = 0.1  # duración del pulso (muy breve)

# =======================================
# INSTRUCCIONES PARA CONFIGURAR TELEGRAM
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
# =======================================

MPU = 0x68  # Direccion I2C del MPU6050

# ===========================
# CONFIGURACIÓN DEL HARDWARE
# ===========================
def inicializar_hardware():
    global buzzer_pin, boton, i2c, wifi

    buzzer_pin = Pin(16, Pin.OUT)
    buzzer_pin.value(1)   # 1 = APAGADO de inmediato
    boton  = Pin(14, Pin.IN, Pin.PULL_UP)

    i2c = I2C(0, scl=Pin(5), sda=Pin(4), freq=400000)
    i2c.writeto_mem(MPU, 0x6B, b'\x00')   # Despierta el acelerómetro

    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)

# ========================
# FUNCIONES DE BUZZER
# ========================

def buzzer_on(frecuencia=None):
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
 

    Reintenta una vez más si falla (con una pequeña pausa), porque
    justo después de reconectar el WiFi, el router ya da conexión.
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

def esperar_toque_con_pitido(segundos, pitido_on=PITIDO_ON_CANCELACION, pitido_off=PITIDO_OFF_CANCELACION):
    """
    Igual que esperar_un_toque(), pero además hace sonar el buzzer en
    pitidos repetidos durante toda la espera (no solo al principio),

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

        # Alternamos encendido/apagado del buzzer sin bloquear la revisión del botón (revisamos cada pocos milisegundos)
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
    Contiene todo el programa: conexión WiFi, mensaje inicial y el bucle principal. Se ejecuta dentro de un bucle exterior 
    que atrapa si algo falla de forma grave y así el dispositivo nunca se queda apagado/muerto mientras tenga batería.
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
            # Truco anti-apagado del power bank: cada cierto tiempo generamos 
            # un pequeño pulso de consumo extra para que el
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
                    # ----------------------------------------------------------------
                    lecturas_verificacion = []
                    inicio_verif = time.time()
                    tiempo_asentamiento = TIEMPO_VERIFICACION * PORCENTAJE_ASENTAMIENTO   # descarta el rebote del golpe

                    while (time.time() - inicio_verif) < TIEMPO_VERIFICACION:
                        a_v, g_v, roll_v, pitch_v, _, _, _ = leer_mpu6050()
                        transcurrido = time.time() - inicio_verif

                        # Solo guardamos lecturas DESPUÉS del asentamiento
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
                        # Si TIEMPO_VERIFICACION es muy corto y no alcanzó a tomar lecturas tras el asentamiento confiable
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
                # PASO 3: VENTANA DE CANCELACIÓN (TIEMPO_CANCELACION segundos)
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
                # PASO 4: EMERGENCIA CONFIRMADA
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


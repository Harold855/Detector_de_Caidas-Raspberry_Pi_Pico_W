# ============================================================
#  DETECTOR DE CAÍDAS v7 — con WiFi + Telegram
#  MicroPython para Raspberry Pi Pico W (o ESP32)
# ============================================================
#
#  MENSAJES QUE SE ENVÍAN A TELEGRAM:
#
#  1. Al detectar movimiento brusco:
#     "⚠️ POSIBLE CAÍDA — [nombre] podría haberse caído.
#      Esperando confirmación... (15 segundos)"
#
#  2. Si la persona presiona el botón entonces está bien:
#     "✅ FALSA ALARMA — [nombre] canceló la alerta. Está bien."
#
#  3. Si nadie la presiona, presunta caída real:
#     "🚨 CAÍDA CONFIRMADA — [nombre] necesita ayuda. ¡Actúen ya!"
#
#  4. Cuando alguien silencia la alarma en el lugar:
#     "🔕 Alarma silenciada en el dispositivo."
#
# ============================================================

from machine import Pin, I2C
import network
import urequests   # Librería HTTP incluida en MicroPython
import time
import math
import struct

# ======================
# ZONA DE CONFIGURACIÓN  
# ======================
# --- Datos de la persona (aparecen en los mensajes de Telegram) ---
NOMBRE_PERSONA = "Abuela María"   # Nombre que podrán ver los familiares

# --- La red WiFi ---
WIFI_NOMBRE   = "COLOCA AQUI EL NOMBRE DE TU RED WIFI"   # El nombre de tu red (SSID)
WIFI_CLAVE    = "COLOCA AQUI LA CLAVE DE TU RED WIFI"      

# --- El bot de Telegram (ver instrucciones para configurar el bot) ---
TELEGRAM_TOKEN   = "COLOCA AQUI EL TOKEN GENERADO POR TU BOT"   # Token de tu bot, ejemplo: "892986...:AAEx3ck...."
TELEGRAM_CHAT_ID = "COLOCA AQUI EL ID DEL CHAT"        # ID del grupo familiar, ejemplo: "-100437..."

# --- Umbrales del detector ---
UMBRAL_CAIDA         = 1.50   # g-force para detectar caída
UMBRAL_GIRO_DPS = 250        # Giro brusco en grados por segundo
UMBRAL_INCLINACION = 55      # Inclinación anormal en grados
TIEMPO_CANCELACION   = 15    # segundos para cancelar con 1 toque
TIEMPO_ALARMA_MAXIMO = 300   # segundos antes de apagarse sola (5 min)

# --- Para silenciar la alarma de emergencia ---
TOQUES_PARA_SILENCIAR = 4    # toques necesarios
VENTANA_TOQUES        = 3.0  # segundos en los que deben ocurrir

# --- Tiempos del pitido ---
PITIDO_ON  = 0.15
PITIDO_OFF = 0.15

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

buzzer = Pin(16, Pin.OUT)
boton  = Pin(14, Pin.IN, Pin.PULL_UP)
buzzer.value(1)   # Empieza apagado (1=apagado en lógica invertida)

i2c = I2C(0, scl=Pin(5), sda=Pin(4), freq=400000)
MPU = 0x68
i2c.writeto_mem(MPU, 0x6B, b'\x00')   # Despierta el acelerómetro

# ========================
# FUNCIONES DE BUZZER
# ========================

def buzzer_on():
    buzzer.value(0)   # 0 = encendido (lógica invertida)

def buzzer_off():
    buzzer.value(1)   # 1 = apagado

# =============================
# FUNCIÓN: CONECTAR AL WIFI
# =============================

def conectar_wifi():
    """
    Conecta al WiFi y espera hasta que haya conexión.
    Muestra un punto cada segundo mientras espera.
    Si no conecta en 20 segundos, continúa sin internet
    (el detector sigue funcionando, solo sin Telegram).
    """
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)
    wifi.connect(WIFI_NOMBRE, WIFI_CLAVE)

    print(f"Conectando a WiFi '{WIFI_NOMBRE}'", end="")
    intentos = 0
    while not wifi.isconnected() and intentos < 20:
        print(".", end="")
        time.sleep(1)
        intentos += 1

    if wifi.isconnected():
        print(f"\n WiFi conectado — IP: {wifi.ifconfig()[0]}\n")
        return True
    else:
        print("\n No se pudo conectar al WiFi. Sin alertas Telegram.\n")
        return False

# =======================================
# FUNCIÓN: ENVIAR MENSAJE A TELEGRAM
# =======================================

def enviar_telegram(mensaje):
    """
    Envía un mensaje al grupo de Telegram usando GET con URL.
    Es el mismo método que funciona en el navegador.
    Si falla, imprime el error y continúa sin detener el detector.
    """
    try:
        # Limpiamos caracteres especiales que rompen la URL
        msg = mensaje
        for orig, repl in [(" ", "%20"), ("\n", "%0A"), ("á","a"), ("é","e"),
                           ("í","i"), ("ó","o"), ("ú","u"), ("ñ","n"),
                           ("¡",""), ("¿",""), ("<b>",""), ("</b>",""),
                           ("⚠️","AVISO"), ("🚨","EMERGENCIA"),
                           ("✅","OK"), ("🔕","SILENCIADO"), ("⏱️","TIEMPO"),
                           ("😊","")]:
            msg = msg.replace(orig, repl)

        url = (f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
               f"?chat_id={TELEGRAM_CHAT_ID}&text={msg}")

        respuesta = urequests.get(url, timeout=10)
        respuesta.close()
        print(f"  [Telegram] Enviado OK")
    except Exception as e:
        print(f"  [Telegram] Error: {e}")
        # No hacemos nada más — el detector sigue funcionando

# ==========================================
# FUNCIÓN: LEER EL ACELERÓMETRO MPU-6050
# ==========================================

def leer_mpu6050():
    """
    -------------------------------------------------
    Lectura del acelerómetro y giroscopio del MPU6050.
    
    Devuelve:
    -> aceleracion_total: magnitud de aceleración en g
    -> giro_total: magnitud del giro en grados/segundo
    -> roll: inclinación lateral
    -> pitch: inclinación frontal
    -> gx, gy, gz: giroscopio por eje
    -------------------------------------------------
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

# ============================================================
# FUNCIÓN: ESPERAR SECUENCIA DE VARIOS TOQUES (para silenciar)
# ============================================================

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

# ==========================
# INICIO DEL PROGRAMA
# ==========================

print("==================================")
print(f"  DETECTOR DE CAÍDAS v7")
print(f"  Persona: {NOMBRE_PERSONA}")
print(f"  1 toque       → cancela alerta")
print(f"  {TOQUES_PARA_SILENCIAR} toques en {VENTANA_TOQUES}s → silencia emergencia")
print("==================================\n")

wifi_ok = conectar_wifi()   # Intentamos conectar al WiFi al arrancar

if wifi_ok:
    # Mensaje de prueba para confirmar que Telegram funciona
    enviar_telegram(f"✅ Dispositivo de <b>{NOMBRE_PERSONA}</b> conectado y listo.")

# =================
# BUCLE PRINCIPAL
# =================

while True:
    try:
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
        # PASO 1: ¿Se detectó una posible caída?
        # --------------------------------------------------------
        inclinacion = max(abs(roll), abs(pitch))

        posible_caida = (accel > UMBRAL_CAIDA or giro > UMBRAL_GIRO_DPS or inclinacion > UMBRAL_INCLINACION)

        if posible_caida:
            print("\n>>> ¡POSIBLE CAÍDA DETECTADA! <<<")

            if accel > UMBRAL_CAIDA:
                print("Motivo: se detectó una aceleración alta:", round(accel, 2), "g")

            if giro > UMBRAL_GIRO_DPS:
                print("Motivo: se detectó un giro brusco:", round(giro, 2), "°/s")

            if inclinacion > UMBRAL_INCLINACION:
                print("Motivo: se detectó una inclinación anormal:", round(inclinacion, 2), "°")
                
            buzzer_on()   # Sonido continuo mientras esperamos respuesta

            # Enviamos PRIMER MENSAJE: posible caída, aún sin confirmar
            enviar_telegram(
                f"⚠️ <b>POSIBLE CAÍDA — {NOMBRE_PERSONA}</b>\n"
                f"Podría haberse caído. Esperando confirmación...\n"
                f"({TIEMPO_CANCELACION} segundos para cancelar)"
            )

            # ------------------------------------------------------------------
            # PASO 2: VENTANA DE CANCELACIÓN (15 segundos)
            # 1 solo toque = la persona está bien, entonces es una falsa alarma
            # ------------------------------------------------------------------
            cancelada          = False
            inicio_cancelacion = time.time()

            while (time.time() - inicio_cancelacion) < TIEMPO_CANCELACION:
                restante = TIEMPO_CANCELACION - int(time.time() - inicio_cancelacion)
                print(f"  Presiona 1 vez para cancelar: {restante}s")

                if esperar_un_toque(2.0):
                    print("\n>>> ALERTA CANCELADA — Persona estable <<<\n")
                    buzzer_off()
                    cancelada = True

                    # Enviamos SEGUNDO MENSAJE: falsa alarma, tranquilos
                    enviar_telegram(
                        f"✅ <b>FALSA ALARMA — {NOMBRE_PERSONA}</b>\n"
                        f"Canceló la alerta ella misma. Está bien. 😊"
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
                    f"🚨 <b>¡CAÍDA CONFIRMADA — {NOMBRE_PERSONA}!</b>\n"
                    f"No respondió en {TIEMPO_CANCELACION} segundos.\n"
                    f"<b>¡Vayan a ayudarla de inmediato!</b>\n"
                    f"La alarma sonará hasta que alguien llegue."
                )

                inicio_alarma = time.time()
                silenciada    = False

                while (time.time() - inicio_alarma) < TIEMPO_ALARMA_MAXIMO:

                    # Ciclo de pitido intermitente de emergencia
                    buzzer_on()
                    time.sleep(PITIDO_ON)
                    buzzer_off()
                    time.sleep(PITIDO_OFF)

                    # Revisamos si alguien hace la secuencia de toques
                    if esperar_secuencia_toques(2.0):
                        silenciada = True
                        print("\n>>> SECUENCIA CORRECTA — Alarma silenciada <<<\n")
                        buzzer_off()

                        # Enviamos CUARTO MENSAJE: alguien llegó y silenció
                        enviar_telegram(
                            f"🔕 <b>Alarma silenciada — {NOMBRE_PERSONA}</b>\n"
                            f"Alguien está con ella en el lugar."
                        )
                        break

                if not silenciada:
                    # Se acabó el tiempo máximo
                    print(f"\n>>> Tiempo máximo ({TIEMPO_ALARMA_MAXIMO}s). Alarma apagada. <<<\n")
                    buzzer_off()
                    enviar_telegram(
                        f"⏱️ <b>Alarma apagada automáticamente — {NOMBRE_PERSONA}</b>\n"
                        f"Se alcanzó el tiempo máximo ({TIEMPO_ALARMA_MAXIMO}s).\n"
                        f"Verifiquen su estado."
                    )

                time.sleep(1)

        time.sleep(0.2)   # Leemos la aceleración 5 veces por segundo

    except Exception as e:
        print("Error:", e)
        buzzer_off()
        time.sleep(2)


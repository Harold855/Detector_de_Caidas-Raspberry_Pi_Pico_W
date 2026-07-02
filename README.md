# Sistema IoT de Detección de Caídas para Adultos Mayores

## Descripción

Este proyecto consiste en la implementación de un sistema con microcontrolador, codificado en MicroPython, en un dispositivo portátil. Este sistema usa una Raspberry Pi Pico W, un sensor MPU6050, ,un buzzer, un botón de cancelación y un bot de Telegram para enviar alertas a un grupo familiar.

## Razón de Creación o Problema Principal

Las caídas en adultos mayores pueden ocurrir cuando la persona se encuentra sola o sin supervisión. Y en algunos casos, la persona puede tener dificultad para levantarse o incluso pueden quedar incapaces de pedir ayuda. Por ello, este sistema busca alertar rápidamente, mediante un mensaje a los familiares en un grupo de Telegram, cuando se detecta un movimiento brusco relacionado con una posible caída.

## Usuario objetivo

El sistema está dirigido principalmente a adultos mayores que normalmente permanecen solos en casa. También beneficia a familiares o cuidadores, ya que les permite recibir alertas mediante Telegram.

## Componentes usados

|**Componente**|**Función**|
|-|-|
|Microcontrolador Raspberry Pi Pico W|Controla el sistema y se conecta a interne|
|Módulo IMU MPU6050|Detecta aceleración, giro e inclinación |
|Buzzer/Zumbador|Emite la alarma sonora|
|Botón pulsador|Cancela falsas alarmas o silencia la alarma|
|Powerbank|Alimenta el sistema|
|Carcasa impresa en 3D|Protege los componentes y permite colocarlo en una correa|

## Funcionamiento

El sistema lee constantemente los valores del MPU6050. La detección no se basa solo con un golpe o movimiento brusco. Primero, el sistema revisa si hubo un giro fuerte acompañado de movimiento. Luego, durante unos segundos, verifica si la persona quedó en una postura anormal y con poca movilidad.
Si estas condiciones se cumplen, el sistema interpreta que puede tratarse de una posible caída. En ese momento, el buzzer emite una alarma y el bot de Telegram envía un mensaje de posible caída al grupo familiar.
Después, el sistema espera 5 segundos para que la persona pueda cancelar la alerta con un toque en el botón. Si presiona el botón, se envía un mensaje de falsa alarma. Si no lo presiona, el sistema confirma la emergencia y envía un mensaje urgente al grupo familiar.
Además, el programa revisa periódicamente la conexión Wi-Fi. Si se desconecta, intenta reconectarse. También incluye un pequeño pulso del buzzer para evitar que algunos powerbanks se apaguen automáticamente por bajo consumo.

## Mensajes de Telegram

El bot puede enviar los siguientes mensajes:

* Dispositivo conectado y listo
* Posible caída detectada
* Falsa alarma cancelada
* Caída confirmada
* Alarma silenciada

## Cómo puedes ejecutar el proyecto

Si deseas ejecutar el proyecto por tu cuenta, debes seguir estos 7 pasos:

1. Instalar MicroPython en la Raspberry Pi Pico W
2. Abrir Thonny
3. Copiar el código en la Pico W
4. Guardar el archivo como "main.py"
5. Conectar el circuito según el diagrama
6. Conectar la Pico W a una laptop o powerbank
7. Verificar que el bot envíe mensajes al grupo de Telegram

## Seguridad de credenciales

Por seguridad, no se deben subir al repositorio los datos reales de Wi-Fi ni el token del bot de Telegram. Por lo que, el archivo con los datos reales solo debe usarse en la Raspberry Pi Pico W.

WIFI_NOMBRE = "COLOCA AQUI EL NOMBRE DE TU WIFI"
WIFI_CLAVE = "COLOCA AQUI LA CLAVE TU WIFI"
TELEGRAM_TOKEN = "COLOCA AQUI EL TOKEN GENERADO POR TU BOT"
TELEGRAM_CHAT_ID = "COLOCA AQUI TU ID DEL CHAT"

## Diagrama de conexiones

|Componente|Pin en Raspberry Pi Pico W|
|-|-|
|MPU6050 SDA|GP4|
|MPU6050 SCL|GP5|
|MPU6050 VCC|3V3|
|MPU6050 GND|GND|
|Botón Pulsador|GP14 y GND|
|Buzzer|GP16, 3V3 y GND|
|Powerbank|Puerto Micro USB de la Pi Pico W|

## Diagrama de flujo del sistema

```mermaid
flowchart TD 
   A[Inicio del sistema] --> B[Inicializar hardware] 
   B --> C[Conectar a Wi-Fi] 
   C --> D[Enviar mensaje: dispositivo listo] 
   D --> E[Leer MPU6050] 
   
   E --> F{¿Hay giro brusco y movimiento fuerte?} 
   
   F -- No --> E 
   F -- Sí --> G[Verificar postura e inmovilidad]
   G --> H{¿Postura anormal y persona quieta?} 
   H -- No --> E 
   H -- Sí --> I[Activar buzzer y enviar posible caída] 
   
   I --> J{¿Botón presionado en 5 segundos?} 
   
   J -- Sí --> K[Cancelar alerta] 
   K --> L[Enviar falsa alarma a Telegram]
   L --> E 
   
   J -- No --> M[Confirmar emergencia] 
   M --> N[Enviar caída confirmada a Telegram] 
   N --> O[Sonar alarma tipo sirena]
   
   O --> P{¿Secuencia de toques para silenciar?} 
   
   P -- Sí --> Q[Silenciar alarma]
   Q --> R[Enviar alarma silenciada a Telegram]
   R --> E 
   
   P -- No --> S{¿Pasaron 5 minutos?} 
   S -- No --> O 
   S -- Sí --> T[Apagar alarma automáticamente] 
   T --> U[Enviar aviso final a Telegram] 
   U --> E

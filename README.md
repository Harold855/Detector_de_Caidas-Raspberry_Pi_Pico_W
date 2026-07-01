# Sistema IoT de Detección de Caídas para Adultos Mayores

## Descripción

Este proyecto consiste en la implementación de un sistema con microcontrolador, codificado en MicroPython, en un dispositivo portátil. Este sistema usa una Raspberry Pi Pico W, un sensor MPU6050, ,un buzzer, un botón de cancelación y un bot de Telegram para enviar alertas a un grupo familiar.

##Razón de Creación o Problema Principal

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
|Batería Recargable/Powerbank|Alimenta el sistema|
|Carcasa impresa en 3D|Protege los componentes y permite colocarlo en una correa|

## Conexiones del circuito

|Componente|Pin en Raspberry Pi Pico W|
|-|-|
|MPU6050 SDA|GP4|
|MPU6050 SCL|GP5|
|MPU6050 VCC|3V3|
|MPU6050 GND|GND|
|Botón|GP14|
|Buzzer|GP16|
|Alimentación|Micro USB mediante powerbank|

## Funcionamiento

El sistema lee constantemente los movimientos del MPU6050. Si este detecta una aceleración fuerte, un giro brusco o una inclinación anormal, entonces activa el buzzer y envía un mensaje de posible caída al grupo familiar de Telegram.

Después de eso, el sistema espera 15 segundos. Si la persona llega a presionar el botón, se cancela la alerta y se envía un mensaje de falsa alarma. Si no lo presiona a tiempo, entonces el sistema confirma la caída y envía una alerta de emergencia.

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

## Estructura de archivos de este repositorio

```text
Detector_de_caidas-Raspberry_Pi_Pico_W/
│
├── README.md
├── main.py
├── diagramas/
│   ├── diagrama_conexiones.png
│   └── diagrama_bloques.png
├── carcasa_3d/
│   └── carcasa.stl
├── evidencias/
│   ├── prototipo.jpg
│   └── telegram.png
├── paper/
│   └── paper_detector_caidas.pdf
└── presentacion/
    └── presentacion_detector_caidas.pptx



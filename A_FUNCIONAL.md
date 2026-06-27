
# Autotester - Sistema de Gamificación para Memorización de PDFs 

## Descripción General

Autotester es un sistema interactivo tipo Duolingo que ayuda al usuario a memorizar el contenido de sus PDFs mediante preguntas generadas automáticamente. El progreso se mide de 0 a 100% y se muestra en una barra de progreso junto al título del proyecto en el panel central.

---

## Flujos Principales

### Flujo 1: Preparación Automática del Contenido
1. El usuario sube un PDF a la aplicación
2. El sistema extrae automáticamente el texto del documento
3. El contenido se divide en párrafos de 100-150 palabras, agrupando conceptos relacionados
4. Para cada párrafo, el sistema genera automáticamente varias preguntas de diferentes tipos
5. El usuario puede comenzar a jugar inmediatamente después de la preparación

### Flujo 2: Inicio del Juego
1. El usuario selecciona un proyecto desde el panel izquierdo
2. El panel central muestra el título del proyecto y una barra de progreso (0-100%)
3. Se presentan las preguntas del primer párrafo de forma interactiva
4. El usuario responde cada pregunta según su tipo (opción múltiple, verdadero/falso, etc.)

### Flujo 3: Progresión y Desbloqueo
1. El usuario debe responder correctamente al menos una vez todas las preguntas de un párrafo para desbloquear el siguiente
2. Una vez desbloqueado el nuevo párrafo, sus preguntas se intercalan con las de párrafos anteriores
3. El sistema refuerza el aprendizaje mostrando preguntas de párrafos ya vistos junto con las nuevas
4. La barra de progreso se incrementa con cada respuesta correcta

### Flujo 4: Repetición Espaciada
1. Cada pregunta debe ser respondida correctamente 3 veces para considerarse "asimilada"
2. Si el usuario falla una pregunta, no puntúa y volverá a aparecer más adelante (hasta 2 veces más)
3. Las preguntas falladas se reprograman automáticamente para reforzar el aprendizaje
4. El sistema prioriza preguntas no asimiladas sobre las ya dominadas

### Flujo 5: Finalización
1. El proyecto se considera completado cuando todas las preguntas de todos los párrafos han sido respondidas correctamente 3 veces
2. La barra de progreso alcanza el 100%
3. El usuario puede reiniciar el progreso en cualquier momento para volver a practicar desde el principio

---

## Requerimientos Funcionales

### Requerimientos de Configuración
1. El idioma de las preguntas debe ser configurable (por defecto: español)
2. El número de preguntas por párrafo debe ser configurable (por defecto: 5)
3. El número de respuestas correctas necesarias para asimilar debe ser configurable (por defecto: 3)
4. El modelo de IA utilizado para generar preguntas debe ser configurable

### Requerimientos de Generación de Contenido
5. Los párrafos deben tener entre 100-150 palabras aproximadamente
6. Los conceptos relacionados deben mantenerse en el mismo párrafo cuando sea posible
7. Cada párrafo debe generar preguntas de diferentes tipos
8. Las respuestas correctas deben pre-calcularse al generar las preguntas
9. Si la IA no está disponible, el sistema debe reintentar 3 veces antes de mostrar error

### Requerimientos de Interfaz
10. La barra de progreso (0-100%) debe mostrarse junto al título del proyecto en el panel central
11. Las preguntas deben presentarse de forma interactiva y secuencial
12. El usuario debe recibir feedback inmediato al responder (correcto/incorrecto)
13. Debe existir un botón para reiniciar el progreso del proyecto
14. Al seleccionar un proyecto, el usuario continúa exactamente donde lo dejó

### Requerimientos de Lógica del Juego
15. Inicialmente solo el primer párrafo está desbloqueado
16. Para desbloquear el siguiente párrafo, el usuario debe acertar al menos una vez todas las preguntas del párrafo actual
17. Cada pregunta debe responderse correctamente 3 veces para considerarse asimilada
18. Las preguntas falladas no puntúan y se reprograman para aparecer más adelante
19. Las preguntas de párrafos anteriores se intercalan con las nuevas hasta alcanzar las 3 respuestas correctas
20. El progreso debe calcularse como: (aciertos totales / (párrafos × preguntas × 3)) × 100

### Requerimientos de Persistencia
21. El progreso del usuario debe guardarse automáticamente
22. El histórico de preguntas y respuestas debe mantenerse
23. Al reabrir un proyecto, el usuario debe continuar desde su último estado
24. El reinicio del progreso debe borrar todo el histórico y comenzar desde 0%

---

## Tipos de Preguntas

Las preguntas deben estar enfocadas a la memorización del contenido

1. **Opción múltiple** — Seleccionar la respuesta correcta entre varias opciones
2. **Verdadero/Falso** — Determinar si una afirmación es correcta o incorrecta
3. **Completar frase** — Rellenar el espacio en blanco con la palabra o concepto correcto
4. **Pregunta abierta corta** — Responder con 1-3 palabras clave

---

## Reglas de Puntuación

- **Total de puntos posibles** = Número de párrafos × Preguntas por párrafo × 3 repeticiones
- **Valor de cada acierto** = 100 / Total de puntos posibles
- **Progreso actual** = Suma de aciertos × Valor de cada acierto
- **Párrafo desbloqueado** = Todas sus preguntas respondidas correctamente al menos 1 vez
- **Pregunta asimilada** = Respondida correctamente 3 veces
- **Proyecto completado** = Todas las preguntas asimiladas (100%)

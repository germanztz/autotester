# Evolutivos - Autotester

**Estado actual:** v1.0 - Funcionalidades base completadas

## ✅ Completados

✅ **#001 - Estructura base de la aplicación**
  - **Descripción:**
    - Layout principal responsive
    - Menú de navegación superior
    - Subida de archivos PDF
    - Visualización de proyectos/archivos
    - Renombrar y eliminar proyectos
    - Sistema de configuración
    - Selector de temas (claro/oscuro/sistema)
    - Suite de tests

✅ **#002 - Integración de IA y Base de Datos Vectorial**
  - **Descripción:** 
    Añadir funcionalidades de IA para indexar el contenido de los PDFs en una base de datos vectorial local. Se utilizará Ollama (modelo `qwen3-embedding:4b`) para generar los embeddings y ChromaDB para almacenarlos localmente dentro de la carpeta del proyecto.
  - **Criterios de aceptación:**
    - **Configuración:** Añadir sección `ia` en `config.yaml` con los siguientes campos:
      - `ollama_url` (por defecto: `http://localhost:11434`)
      - `embedding_model` (por defecto: `qwen3-embedding:4b`)
      - `chunk_size` (por defecto: `500`)
      - `chunk_overlap` (por defecto: `50`)
      - *(Asunción: Al guardar la configuración, se validará que la URL de Ollama es accesible llamando a `/api/tags`. Si falla, se muestra advertencia).*
    - **Procesamiento (Digestión):**
      - Al subir un PDF, extraer el texto usando `PyMuPDF`.
      - Dividir el texto en chunks según `chunk_size` y `chunk_overlap`.
      - Generar embeddings y guardarlos en ChromaDB en la ruta `./projects/<nombre_proyecto>/chroma.db`.
      - **Flujo asíncrono:** Mostrar un indicador "Procesando PDF... (xx s)" en el panel central. e ir actualizando xx s por los segundos que esta tardando en procesar. Al finalizar, reemplazarlo con un resumen.
      - **Resumen:** Debe mostrar número de páginas procesadas, número de chunks/vector insertados y tiempo total. *(Asunción: El resumen persiste en la vista del proyecto hasta que se recargue la página).*
      - **Restricciones:** Si Ollama no está disponible, devolver error inmediato al usuario.
    - **Arquitectura:**
      - Toda la lógica de IA segregada en `app/controllers/ai_controller.py` y `app/models/ai_manager.py`.
    - **Testing (TDD):**
      - Crear los tests necesarios
  - **Prioridad:** Media

✅ **#003 - BUG: Error when embed file**
  - **Descripción:** 
    - is not createing chrome.db file
    - OllamaUnavailable: Ollama unreachable at http://localhost:11434 

✅ **#004 - Logging into console**
  - **Descripción:** 
    - log actions as info
    - add log section with loglevel in config default info

✅ **005 - Embedding perezoso (lazy) página por página**
  - **Descripción:** Modificar el proceso de digestión para que la generación de embeddings sea incremental (página por página) en lugar de procesar todo el documento de una sola vez. Esto actuará como un mecanismo de checkpoint para optimizar memoria y permitir retomar el proceso si se interrumpe.
  - **Criterios de Aceptación:**
    1. **Procesamiento incremental:** No incrustar (embed) todas las páginas del PDF de forma simultánea.
    2. **Archivo intermedio:** Generar primero un archivo `<nombre_archivo>.md` que contenga el texto extraído del PDF original.
    3. **Marcadores de página:** En el archivo `.md`, separar el contenido de cada página utilizando el marcador `### Page $number` (donde `$number` es el número de página).
    4. **Búsqueda y procesamiento:** Al iniciar el embedding, buscar el primer marcador `### Page $number` y procesar el contenido hasta encontrar el siguiente marcador o llegar al final del archivo (EOF).
    5. **Limpieza de marcadores:** Una vez que el contenido de una página haya sido incrustado en la base de datos vectorial, eliminar su marcador `### Page $number` del archivo `.md` para evitar que se vuelva a procesar.
    6. **Estado final:** Al finalizar el procesamiento de todo el documento, no debe quedar ningún marcador `### Page $number` en el archivo `<nombre_archivo>.md`.
    7. **Panel Izquierdo (Sidebar):**
       - El proyecto se añade al panel izquierdo **antes** de que comience la digestión.
       - Mostrar el progreso de la digestión (ej: "Processing page X...") directamente en el elemento del proyecto en el sidebar.
       - Añadir un icono de acción (ej. stop/cancel) en el elemento del sidebar para **detener la digestión** mientras esté activa.
       - Una vez finalizada la digestión (o cancelada), eliminar automáticamente el icono de acción de detener.
    8. **Panel Central:**
       - **Eliminar** cualquier indicador de progreso de la digestión en el panel central.
       - Al finalizar la digestión, mostrar un resumen estático: Creación de la BD y número de elementos (chunks) añadidos.
    9. **Textos de UI en Inglés** (cumplir AGENTS.md).

✅ **#009 - BUG Ollama URL config no se tiene en cuenta**
  - **Descripción:** la url de ollama se ha cambiado a http://localhost:31434 en la pagina de fonciguracion, pero la conexions falla.
  se tuede ver un error : ERROR    autotester | Job 9e8f1138eb814116aaacdec11edf9e9c failed: OllamaUnavailable: Ollama unreachable at http://localhost:11434 (after 3 attempts)


✅ **#007 - Unificar botones de guardado en la vista de configuración**
  - **Descripción:** Refactorizar la vista de configuración para eliminar los múltiples botones de "Guardar" actuales. Implementar un único botón de guardado que persista todos los cambios de la configuración (tema, ajustes de IA, chunking, etc.) en el `config.yaml` de una sola vez.
  - **Criterios de Aceptación:**
    1. Eliminar todos los botones de guardado individuales existentes en la página de configuración.
    2. Añadir un único botón "Save Settings" al final del formulario de configuración.
    3. Al hacer clic en el botón, se deben validar y guardar todos los campos del formulario en el `config.yaml`.
    4. Mostrar feedback visual (ej. toast de éxito o error) tras intentar guardar.
  - **Prioridad:**  🟡 Media

✅ **#008 - Eliminar notificación flotante durante la digestión de PDF**
  - **Descripción:** Eliminar el toast o notificación flotante que aparece actualmente durante el proceso de digestión del PDF. Dado que el progreso ya se muestra de forma nativa en el panel izquierdo (sidebar) según la issue #002, esta notificación flotante es redundante y ensucia la interfaz.
  - **Criterios de Aceptación:**
    1. Identificar y eliminar el componente de notificación flotante (toast/alert) asociado al estado de digestión.
    2. Verificar que el progreso de la digestión se sigue mostrando correctamente en el sidebar.
    3. Limpiar cualquier código JavaScript o CSS huérfano que se usara exclusivamente para gestionar esta notificación flotante.
  - **Prioridad:** 🟡 Media

✅ **#009 - Limpiar panel central y mostrar título del proyecto seleccionado**
  - **Descripción:** Refactorizar la vista por defecto del panel central para eliminar el "clutter" inicial. El panel central debe dejar de mostrar información estática y su título debe reflejar dinámicamente el proyecto que el usuario tiene seleccionado en el sidebar.
  - **Criterios de Aceptación:**
    1. Eliminar el título estático "Dashboard" del panel central.
    2. Eliminar el mensaje de bienvenida (welcome message).
    3. Eliminar la indicación de texto "Port 6444" de la parte superior derecha de la pantalla.
    4. Eliminar el botón "+ Add PDF" a la derecha del titulo del panel central.
    5. El encabezado/título del panel central debe mostrar dinámicamente el nombre del proyecto seleccionado en el sidebar.
    6. Si no hay ningún proyecto seleccionado, el panel central debe mostrar un estado vacío limpio (o el nombre de la aplicación) sin los elementos eliminados.
  - **Prioridad:** 🟡 Media  

✅ **006 - Sistema de cola de digestión con polling y procesamiento secuencial**
  - **Descripción:** Implementar un mecanismo de fondo que, al iniciar la aplicación y posteriormente cada minuto, revise el estado de todos los proyectos para garantizar que todos los PDFs queden completamente digeridos. Solo se permite un trabajo de digestión activo a la vez en toda la aplicación (una página por vez).
  - **Criterios de Aceptación:**
    1. **Polling periódico:** Al arrancar la aplicación y, posteriormente, cada 60 segundos, comprobar el estado de todos los proyectos existentes.
    2. **Digestión secuencial (una página a la vez):** Si ya hay un trabajo de digestión activo en la aplicación, no iniciar ningún otro. Solo se procesa una página por vez en toda la aplicación.
    3. **Generación del archivo intermedio:** Si un proyecto no tiene creado el archivo `<nombre>.md` con el contenido extraído y las marcas `### Page $number`, debe generarlo antes de empezar a digerir.
    4. **Digestión incremental:** Si el archivo `.md` ya existe pero aún contiene marcas de página sin procesar, continuar digiriendo las páginas faltantes y añadirlas al `chroma.db` respetando el orden.
    5. **Estado final consistente:** El ciclo de comprobación debe continuar hasta que todos los proyectos cumplan:
       - El archivo `.md` no contiene ninguna marca `### Page $number` pendiente.
       - Todas las páginas están procesadas e insertadas en el `chroma.db`.
    6. **Auto-parada del polling:** Una vez que todos los proyectos estén en estado final (sin marcas pendientes y con el `chroma.db` completo), el sistema cambiará el periodo de las comprobaciones periódicas de 60 a 600 segundos.
    7. **Feedback en UI:** El panel izquierdo debe reflejar el estado real de cada proyecto (x = paginas procesadas, y= paginas totales del pdf, status=queued|error):
       - icono in progress,  en el div project-status :"{x}/{y} {status}" si no está completada la digestion
       - icono tic verde, en el div project-status : "{y} pages" si está completada la digestion.
       - icono tic warning, en el div project-status : "Error", Si un proyecto falla durante la digestión
    8. **Manejo de errores:** Si un proyecto falla durante la digestión, debe marcarse como error y no bloquear el procesamiento de los demás proyectos en la cola.

✅ **#010 - Logging de procesos en background y cambios de estado**
  - **Descripción:** Implementar un sistema de logging en nivel `INFO` por consola para monitorizar procesos en segundo plano, cambios de estado del sistema y acciones relevantes del usuario. Los logs deben ser claros, estructurados y escritos en inglés (cumpliendo AGENTS.md).
  - **Criterios de Aceptación:**
    1. **Configuración del Logger:**
       - Usar el módulo estándar `logging` de Python.
       - Formateador estándar: `%(asctime)s | %(levelname)s | %(message)s`
       - Nivel por defecto: `INFO`
       - Salida exclusivamente por consola (`sys.stdout`).
    2. **Arranque y Escaneo Inicial:**
       - Al iniciar la aplicación, registrar: `INFO | Scanning ./projects/ for unprocessed pages...`
       - Indicar cuántos proyectos requieren procesamiento tras el escaneo inicial.
    3. **Proceso de Digestión (Página por Página):**
       - Inicio: `INFO | Starting digestion | Document: <doc_name> | Page: <N>`
       - Fin: `INFO | Finished digestion | Document: <doc_name> | Page: <N> | Duration: <X>ms`
    4. **Escaneo Periódico (Polling):**
       - Cada ciclo debe registrar si se encontraron páginas pendientes o no.
       - Si todos los proyectos están al día y el intervalo cambia a `long_interval`, registrar: `INFO | All projects up to date. Switching scan interval to long_interval (<X>s)`
    5. **Ciclo de Vida de Jobs:**
       - Cualquier tarea en background debe loguear su inicio y fin con estado final (`SUCCESS`, `ERROR`, `CANCELLED`) y duración total.
       - Ejemplo fin: `INFO | Digestion job completed | Status: SUCCESS | Total time: <Y>s`
    6. **Acciones de Usuario (Cambios de Estado):**
       - Upload PDF: `INFO | User uploaded PDF | Project: <project_name> | File: <filename.pdf>`
       - Guardar configuración: `INFO | Configuration saved by user`
       - Renombrar proyecto: `INFO | Project renamed | <old_name> -> <new_name>`
       - Eliminar proyecto: `INFO | Project deleted | <project_name>`

  ## 📋 Backlog

- [ ] **#011 - Config section for game settings in config.yaml**
  - **Descripción:** Añadir sección `game` en `config.yaml` con: `language` (defecto: `es`), `questions_per_paragraph` (defecto: `5`), `correct_answers_needed` (defecto: `3`), `question_model`.
  - **Criterios:**
    1. Campos editables desde la vista `/config/` junto a los existentes.
    2. Validación: `questions_per_paragraph` > 0, `correct_answers_needed` > 0.
    3. `update_game()` en `ConfigManager` con persistencia atómica.
    4. Tests con `caplog` y `temp_workspace`.
  - **Prioridad:** 🟡 Media

- [ ] **#012 - Paragraph splitter (100-150 palabras)**
  - **Descripción:** Implementar `ParagraphSplitter` que divida el texto extraído de un PDF en párrafos de 100-150 palabras, manteniendo conceptos relacionados juntos.
  - **Criterios:**
    1. Función `split_into_paragraphs(text: str) -> list[str]` en `app/services/paragraph_splitter.py`.
    2. Cada párrafo entre 100-150 palabras (salvo el último si el texto se acaba).
    3. Heurística básica: no cortar a mitad de frase; agrupar por límite de oración.
    4. Tests con textos cortos, largos y exactos.
  - **Prioridad:** 🟡 Media

- [ ] **#013 - Question generation via Ollama**
  - **Descripción:** Para cada párrafo, generar automáticamente preguntas de los 4 tipos (opción múltiple, V/F, completar frase, abierta corta) usando Ollama. Pre-calcular respuestas correctas. Reintentar 3 veces si la IA falla.
  - **Criterios:**
    1. Función `generate_questions(paragraph: str, count: int, model: str, lang: str) -> list[dict]` en `app/services/question_generator.py`.
    2. Cada pregunta incluye: `type`, `question_text`, `options` (si aplica), `correct_answer`.
    3. Reintentos: hasta 3 intentos con exponential backoff ante error de Ollama.
    4. Tests con `FakeOllama` que devuelva JSON válido simulado.
  - **Prioridad:** 🟡 Media

- [ ] **#014 - Question data model and persistence**
  - **Descripción:** Definir la estructura de datos para preguntas y progreso. Persistir en `projects/<name>/game.json`.
  - **Criterios:**
    1. Campos por pregunta: `id`, `type`, `paragraph_index`, `text`, `options`, `correct_answer`.
    2. Campos por progreso: `paragraph_states[{index, unlocked, questions_answered_correctly_at_least_once}]`, `question_states[{id, correct_count, assimilated}]`.
    3. Clase `GameStateManager` en `app/models/game_manager.py` con load/save.
    4. Tests de persistencia y carga.
  - **Prioridad:** 🟡 Media

- [ ] **#015 - Game orchestration: pipeline text → paragraphs → questions**
  - **Descripción:** Tras la digestión (Chromadb completa), ejecutar el pipeline: split en párrafos → generar preguntas para cada párrafo → persistir en `game.json`. Solo ejecutar una vez por proyecto.
  - **Criterios:**
    1. El supervisor (o un hook post-digestión) detecta que un proyecto terminó de digerirse y no tiene `game.json` → ejecuta pipeline.
    2. Logs: `INFO | Generating paragraphs for <project>` / `INFO | Generating questions for paragraph <N>` / `INFO | Game ready for <project>`.
    3. Si falla la generación (3 intentos), marcar estado `game_error` en el proyecto.
    4. Tests de integración con FakeOllama.
  - **Prioridad:** 🟡 Media

- [ ] **#016 - Game logic: paragraph unlock and progression**
  - **Descripción:** Implementar la lógica de desbloqueo de párrafos y reglas de progresión.
  - **Criterios:**
    1. Solo el párrafo 0 comienza desbloqueado.
    2. Desbloquear párrafo N+1 cuando todas las preguntas del párrafo N han sido respondidas correctamente al menos 1 vez.
    3. Las preguntas de párrafos anteriores se intercalan con las nuevas hasta alcanzar 3 respuestas correctas (asimilación).
    4. Progreso = `(total_correct / (num_paragraphs × questions_per_paragraph × 3)) × 100`.
    5. Función pura `next_question(state) -> question_id` y `apply_answer(state, question_id, answer) -> new_state` testeable sin IO.
    6. Tests unitarios de la máquina de estados.
  - **Prioridad:** 🟡 Media

- [ ] **#017 - Game logic: answer validation and feedback**
  - **Descripción:** Validar respuesta del usuario, devolver feedback inmediato y gestionar el rescheduling de preguntas falladas.
  - **Criterios:**
    1. `validate_answer(question, user_answer) -> bool`.
    2. Si acierta: incrementar `correct_count`; si llega a 3, marcar `assimilated=True`.
    3. Si falla: no incrementar `correct_count`, la pregunta se reprograma (aparecerá de nuevo tras N preguntas).
    4. `apply_answer` actualiza `question_states` y persiste automáticamente.
    5. Tests.
  - **Prioridad:** 🟡 Media

- [ ] **#018 - UI: Question display in central panel**
  - **Descripción:** Mostrar preguntas de forma interactiva en el panel central al seleccionar un proyecto con juego activo.
  - **Criterios:**
    1. Al seleccionar proyecto en sidebar, si tiene `game.json` cargar la siguiente pregunta.
    2. Renderizar los 4 tipos de pregunta (múltiple, V/F, completar, abierta).
    3. Feedback visual inmediato: verde (acierto) / rojo (fallo) + texto explicativo.
    4. Botón "Next Question" tras el feedback para pasar a la siguiente.
    5. Si no hay juego (proyecto sin digerir o sin preguntas), mostrar mensaje "Game not ready".
    6. Tests con `client` y HTML parseado.
  - **Prioridad:** 🟡 Media

- [ ] **#019 - UI: Progress bar**
  - **Descripción:** Mostrar barra de progreso 0-100% junto al título del proyecto en el panel central, actualizada tras cada respuesta.
  - **Criterios:**
    1. Barra Bootstrap `.progress-bar` animada junto al nombre del proyecto.
    2. Texto dentro de la barra: `"X%"` o `"X% (Y/Z points)"`.
    3. Se actualiza vía el JSON de `/ai/projects` o un nuevo endpoint `/game/status/<project>`.
    4. Tests.
  - **Prioridad:** 🟡 Media

- [ ] **#020 - UI: Progress reset button**
  - **Descripción:** Botón en el panel central para reiniciar el progreso del proyecto seleccionado.
  - **Criterios:**
    1. Botón "Reset Progress" visible solo cuando hay un proyecto con juego activo.
    2. Confirmación con modal "¿Estás seguro? Todo el progreso se perderá."
    3. Al confirmar: resetear `game.json` a estado inicial (0%), mantener preguntas intactas.
    4. Tests con cliente HTTP.
  - **Prioridad:** 🟡 Media

- [ ] **#021 - Game state auto-save and resume**
  - **Descripción:** El estado del juego se guarda automáticamente tras cada respuesta. Al reabrir la aplicación y seleccionar el proyecto, continuar exactamente donde se dejó.
  - **Criterios:**
    1. `GameStateManager.save()` llamado automáticamente por `apply_answer`.
    2. Al seleccionar proyecto, cargar `game.json` y restaurar el estado completo.
    3. Si no hay `game.json`, mostrar estado vacío / preguntas no generadas.
    4. Tests de persistencia entre ciclos.
  - **Prioridad:** 🟡 Media

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

✅ **#011 - Refactorización del Motor de Ingesta - Reemplazo de RAG por Segmentación Semántica con LLM Local**

  - **1. Descripción y Justificación**
  Actualmente, el sistema utiliza una implementación basada en RAG (con ChromaDB) para la ingestión de PDFs. Aunque útil para búsquedas semánticas, este enfoque es un anti-patrón para el flujo secuencial y gamificado de *Autotester*, ya que no garantiza el tamaño de párrafo requerido (100-150 palabras) ni extrae metadatos útiles (keywords) de forma nativa.

  Esta feature sustituye el pipeline de ingesta actual por un proceso de **Segmentación Semántica asistida por LLM Local**. El nuevo flujo procesará el texto crudo mediante un LLM (vía Ollama) para agrupar conceptos, extraer palabras clave y preparar el terreno para una generación de preguntas de alta calidad, eliminando la dependencia de la base de datos vectorial para esta fase y alineándose estrictamente con el `A_FUNCIONAL.md`.

  - **2. Requerimientos Técnicos del Flujo de Ingesta**

  El proceso de ingesta debe ejecutarse siguiendo estrictamente esta secuencia de pasos:

  1.  **Extracción de Texto Crudo:** 
      *   Utilizar la librería `PyMuPDF` (`fitz`) para extraer el texto completo del PDF subido, manteniendo la mayor fidelidad posible al documento original.
  2.  **Pre-procesamiento y Chunking Heurístico:** 
      *   Dividir el texto crudo en bloques (chunks) para ser enviados al LLM. 
      *   *Actualización de Configuración:* Añadir en `config.yaml` los parámetros `chunk_size: 400` (palabras) y `chunk_overlap: 50` (palabras).
  3.  **Procesamiento Secuencial con LLM Local:** 
      *   Iterar sobre los chunks generados y enviarlos individualmente al LLM local utilizando la librería oficial de Python `ollama`.
      *   *Actualización de Configuración:* Añadir en `config.yaml` el parámetro `ollama_model` (por defecto: `qwen3.5:latest` o similar) para permitir la configuración del modelo.
      *   El prompt debe instruir al LLM para que agrupe conceptos, mantenga la coherencia y extraiga palabras clave (keywords).
  4.  **Persistencia Intermedia y Estado:** 
      *   Almacenar la respuesta de cada llamada al LLM de forma incremental en un fichero JSON ubicado en el directorio del proyecto, nombrado `<pdf_filename>_chunks.json`.
      *   La estructura de cada registro en el JSON debe contener:
          *   `original_text`: El texto semántico agrupado/devuelto por el LLM.
          *   `text_keywords`: Lista de palabras clave extraídas.
          *   `last_index`: Índice (en palabras o caracteres) del texto original hasta donde se ha procesado correctamente. Esto permite calcular el progreso y, opcionalmente, reanudar el proceso en caso de caída.
  5.  **Ejecución en Segundo Plano (Background Job):** 
      *   Todo el pipeline (extracción, chunking, llamadas a Ollama y guardado en JSON) debe ejecutarse de forma asíncrona como un *Background Job* para no bloquear el hilo principal de la aplicación web ni la interfaz de usuario.
  6.  **Logging y Trazabilidad:** 
      *   El proceso en segundo plano debe emitir logs estructurados por consola (usando el módulo `logging` de Python), indicando el inicio del proceso, el chunk actual being processed, errores de la API de Ollama y la finalización.

  - **3. Requerimientos de Interfaz de Usuario (UI/UX) - Panel Izquierdo (Sidebar)**

  La UI debe reflejar el estado del *Background Job* en tiempo real (o mediante polling periódico) en la lista de archivos del panel izquierdo:

  1.  **Indicador de Progreso en Tiempo Real:** 
      *   Mientras el job se esté ejecutando, el archivo en el sidebar debe mostrar el texto: `"processing x%"`.
      *   El porcentaje `x` se calculará dinámicamente como: `(last_index actual / total de palabras del PDF original) * 100`.
  2.  **Indicador de Finalización Exitosa:** 
      *   Una vez el proceso llegue al 100% y el JSON esté completo, el indicador de progreso debe desaparecer.
      *   En su lugar, debe mostrarse un **icono de tic verde (✅)** junto al nombre del archivo.
      *   Adicionalmente, debe mostrarse el texto `"x keywords"`, donde `x` es la suma total de todas las palabras clave extraídas y almacenadas en el `<pdf_filename>_chunks.json`.

  - **4. Criterios de Aceptación (Definition of Done)**

  *   [ ] El código legacy de ChromaDB/RAG ha sido eliminado o completamente aislado del flujo de ingesta principal.
  *   [ ] El archivo `config.yaml` incluye y lee correctamente las nuevas variables (`chunk_size`, `chunk_overlap`, `ollama_model`).
  *   [ ] Se genera el fichero `<pdf_filename>_chunks.json` con la estructura exacta requerida (`original_text`, `text_keywords`, `last_index`).
  *   [ ] La ingesta no bloquea la interfaz web (corre en segundo plano).
  *   [ ] Los logs del proceso son visibles en la consola del servidor.
  *   [ ] El sidebar muestra el progreso `"processing x%"` calculado correctamente basado en el `last_index`.
  *   [ ] Al terminar, el sidebar muestra el tic verde ✅ y el recuento total de `"x keywords"`.
  *   [ ] Se han escrito tests unitarios (usando `pytest` y mocks para Ollama) que validan la lógica de chunking, el cálculo del progreso y la estructura del JSON de salida.
  *   [ ] eliminacion del codigo anterior, test unitarios de la implementacion RAG



  ## 📋 Backlog
Como analista de software, he redactado la especificación de la *Feature* (Característica) siguiendo las mejores prácticas de gestión de productos y requisitos técnicos. Está estructurada para ser introducida directamente en un gestor de tareas (como Jira, GitHub Issues o Trello).

---


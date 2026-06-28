# Evolutivos - Autotester

**Estado actual:** v1.0 - Funcionalidades base completadas

## ✅ Completados

✅ **#001** - Estructura base de la aplicación
✅ **#002** - Integración de IA y Base de Datos Vectorial
✅ **#003** - BUG: Error when embed file
✅ **#004** - Logging into console
✅ **#005** - Embedding perezoso (lazy) página por página
✅ **#009** - BUG Ollama URL config no se tiene en cuenta
✅ **#007** - Unificar botones de guardado en la vista de configuración
✅ **#008** - Eliminar notificación flotante durante la digestión de PDF
✅ **#009** - Limpiar panel central y mostrar título del proyecto seleccionado
✅ **#006** - Sistema de cola de digestión con polling y procesamiento secuencial
✅ **#010** - Logging de procesos en background y cambios de estado
✅ **#011** - Refactorización del Motor de Ingesta (RAG → Segmentación Semántica)
✅ **#012** - Modelo de estado de juego (`app/models/game_state.py`)
  - `GameState`, `ParagraphState`, `QuestionRecord` con persistencia
  - Cálculo de progreso, desbloqueo de párrafos, asimilación, repetición espaciada
  - 24 tests unitarios
✅ **#013** - Generador de preguntas vía LLM (`app/services/question_generator.py`)
  - 4 tipos: multiple_choice, true_false, fill_blank, short_answer
  - Reintentos (3x), parseo y validación de JSON
  - 14 tests
✅ **#014** - Config de juego en `config.yaml` 
  - Sección `game` con `language`, `questions_per_paragraph`, `correct_to_master`, `model`
  - Validación + `ConfigManager.update_game()`
  - 11 tests
✅ **#015** - API REST de juego (`app/controllers/game_controller.py`)
  - `POST /game/<name>/start`, `GET /game/<name>/status`, `GET /game/<name>/next`
  - `POST /game/<name>/answer`, `POST /game/<name>/reset`
  - Blueprint registrado en `app/__init__.py`
  - 10 tests
✅ **#016** - QuestionEngine (`app/services/question_engine.py`)
  - Orquestación de generación de preguntas por párrafo
  - `start_game()`, `generate_paragraph_questions()`, `generate_all_questions()`, `get_game_status()`
  - 9 tests
✅ **#017** - UI de Quiz en panel central
  - Barra de progreso Bootstrap, área de preguntas, feedback inmediato
  - Botón "Start Game", "Next", "Reset progress"
  - Pantalla de celebración al 100%, spinner durante generación
  - Renderizado dinámico por JavaScript (sin templates separados)
✅ **#018** - Quiz JS (`app/views/static/js/quiz.js`)
  - Polling de estado cada 2s durante generación
  - Manejo de respuestas: clic en opciones, Enter en texto
  - Feedback visual (correcto/incorrecto) con highlight de respuesta correcta
  - Actualización dinámica de barra de progreso
  - Confirmación antes de reset

---

## 📋 Backlog — Pendiente

### #019 — Sidebar: indicador de estado de juego
- **Descripción:** Mostrar progreso del juego en el sidebar junto a cada proyecto (barra pequeña o porcentaje).
- **Prioridad:** 🟢 Baja

### #020 — Tests de integración del flujo completo
- **Descripción:** Tests E2E: upload → digerir → jugar → progresar → completar → reset.
- **Prioridad:** 🟢 Baja

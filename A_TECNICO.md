Crea una aplicación web completa llamada "autotester" en Python siguiendo estos requisitos:

**ARQUITECTURA Y FRAMEWORK:**
- Usa Flask o FastAPI como framework web principal
- Implementa el patrón MVC (Modelo-Vista-Controlador)
- La aplicación debe correr SIEMPRE en el puerto 6444
- Estructura de carpetas profesional y modular

**INTERFAZ DE USUARIO:**
- Diseño responsive, moderno y profesional (usa Bootstrap 5 o Tailwind CSS)
- Layout con:
  * Barra de menú superior fija
  * Panel izquierdo (sidebar) para lista de archivos
  * Panel central para contenido principal

**MENÚ SUPERIOR:**
1. "Fichero" → Submenú con:
   - "Abrir": Permite añadir/adjuntar un archivo PDF desde el disco local
   
2. "Configuración": 
   - Muestra opciones de configuración en el panel central
   - Selector de tema: Claro / Oscuro / Sistema
   - Guarda la configuración en config.yaml

**FUNCIONALIDAD DEL PANEL IZQUIERDO:**
- Muestra lista de archivos PDF añadidos
- Cada archivo tiene dos iconos de acción:
  * Editar (icono lápiz)
  * Eliminar (icono basura/papelera)
- Los archivos se almacenan en el directorio raíz del proyecto

**GESTIÓN DE ARCHIVOS:**
- Upload de PDFs desde el disco local del usuario
- Los archivos se guardan en el sub directorio ./projects/$filename/ 

**CONFIGURACIÓN:**
- Archivo config.yaml para guardar:
  * Tema seleccionado (claro/oscuro/sistema)
  * Otras configuraciones de la app

**TESTING (TDD):**
- Crea tests para CADA funcionalidad en la carpeta ./tests
- Usa pytest como framework de testing
- Incluye tests para:
  * Upload de archivos
  * CRUD de archivos
  * Configuración de temas
  * Persistencia en YAML
  * Rutas de la aplicación

**REQUISITOS TÉCNICOS ADICIONALES:**
- Usa PyYAML para manejar config.yaml
- Implementa manejo de errores adecuado
- Validación de archivos (solo PDF)
- Feedback visual al usuario (toasts/alertas)
- Código limpio, documentado y siguiendo mejores prácticas

**ENTREGABLES:**
1. Estructura completa del proyecto
2. Todos los archivos necesarios (models, views, controllers, templates, static)
3. Tests en ./tests
4. requirements.txt con dependencias
5. README.md con instrucciones de instalación y uso

**COMANDOS DE EJECUCIÓN:**
- Proporciona el comando para instalar dependencias
- Proporciona el comando para correr tests
- Proporciona el comando para iniciar la app en puerto 6444


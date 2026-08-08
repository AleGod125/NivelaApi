# Nivela API

API inicial de Nivela construida con Flask, Python y Supabase.

Supabase Auth maneja la autenticacion con email/password, Google OAuth y telefono + OTP. Flask no almacena passwords, OTP, tokens de Google ni datos sensibles de `auth.users`.

## Instalacion

```bash
pip install -r requirements.txt
```

## Variables de entorno

Debe existir un archivo `.env` local o variables configuradas en Render:

```env
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SERVICE_ROLE_KEY=
ALLOWED_ORIGINS=http://localhost:4200
ADMIN_USER_IDS=
```

`SUPABASE_KEY` es la publishable key utilizada para validar usuarios con Supabase Auth.

`SUPABASE_SERVICE_ROLE_KEY` se usa solo en Flask para operaciones internas sobre `public.profiles`. Nunca debe enviarse al frontend, imprimirse en logs, hardcodearse ni subirse al repositorio.

## Ejecucion

```bash
python app.py
```

La API queda disponible por defecto en:

```text
http://localhost:5000
```

## Endpoints

```text
GET  /api/health
GET  /api/users
GET  /api/users/<user_id>
POST /api/users
PATCH /api/users/me
GET  /api/exercises/catalog
GET  /api/exercises
GET  /api/exercises/<exercise_id>
POST /api/exercises/<exercise_id>/check
GET  /api/learning-map
POST /api/training/session
GET  /api/training/session/<session_id>/next
POST /api/training/session/<session_id>/answer
GET  /api/billing/me
POST /api/billing/subscribe
POST /api/billing/cancel
POST /api/billing/webhook
```

### GET /api/health

Verifica que Flask este funcionando.

```json
{
  "success": true,
  "message": "Nivela API funcionando"
}
```

### POST /api/users

Crea o devuelve el perfil de Nivela para un usuario autenticado en Supabase. Es idempotente.

Headers:

```http
Authorization: Bearer <supabase_access_token>
Content-Type: application/json
```

Body:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alejandro",
  "full_name": "Alejandro Navarro",
  "avatar_url": null
}
```

Creado:

```json
{
  "success": true,
  "created": true,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "alejandro",
    "full_name": "Alejandro Navarro",
    "avatar_url": null
  }
}
```

Ya existia:

```json
{
  "success": true,
  "created": false,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "alejandro",
    "full_name": "Alejandro Navarro",
    "avatar_url": null
  }
}
```

### GET /api/users

Lista perfiles. Requiere Bearer token y que el usuario autenticado este incluido en `ADMIN_USER_IDS`.

### GET /api/users/<user_id>

Devuelve un perfil por id. Requiere Bearer token. Un usuario puede consultar su propio perfil; usuarios en `ADMIN_USER_IDS` pueden consultar otros perfiles.

### GET /api/exercises/catalog

Devuelve niveles y categorias disponibles para la carrera y especializacion del perfil autenticado.

```bash
curl -H "Authorization: Bearer <token>" http://localhost:5000/api/exercises/catalog
```

### GET /api/exercises

Lista ejercicios publicados sin `solution` ni `explanation`. Los filtros disponibles son `difficulty`, `category` y `type`.

```bash
curl -H "Authorization: Bearer <token>" "http://localhost:5000/api/exercises?difficulty=1&category=anatomia_cardiaca"
```

### GET /api/exercises/<exercise_id>

Devuelve un ejercicio publicado sin `solution` ni `explanation`, siempre que pertenezca a la carrera/especializacion del usuario.

```bash
curl -H "Authorization: Bearer <token>" http://localhost:5000/api/exercises/<exercise_id>
```

### POST /api/exercises/<exercise_id>/check

Corrige una respuesta usando `solution` internamente y devuelve solo si fue correcta y la explicacion.

```bash
curl -X POST http://localhost:5000/api/exercises/<exercise_id>/check \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"answer\":\"d\"}"
```

### GET /api/learning-map

Devuelve niveles y modulos desde `user_module_progress` para la carrera y especializacion del usuario autenticado. Si el usuario aun no tiene progreso para esa ruta profesional, lo inicializa de forma idempotente.

```bash
curl -H "Authorization: Bearer <token>" http://localhost:5000/api/learning-map
```

### POST /api/training/session

Inicia una sesion temporal de modulo y devuelve la primera pregunta sin `solution`.

```bash
curl -X POST http://localhost:5000/api/training/session \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"difficulty\":1,\"module\":1}"
```

### GET /api/training/session/<session_id>/next

Devuelve otra pregunta aleatoria de la sesion, priorizando preguntas no vistas. No devuelve `solution`.

```bash
curl -H "Authorization: Bearer <token>" http://localhost:5000/api/training/session/<session_id>/next
```

### POST /api/training/session/<session_id>/answer

Corrige la pregunta actual, actualiza contadores en la sesion temporal, suma XP por respuesta correcta y completa/desbloquea modulos cuando alcanza el objetivo.

```bash
curl -X POST http://localhost:5000/api/training/session/<session_id>/answer \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"exercise_id\":\"<exercise_id>\",\"answer\":\"d\"}"
```

XP actual:

```text
respuesta correcta: +5 XP
primera completacion de modulo: +50 XP
Nivela Plus: XP x2
```

El bonus de completacion solo se entrega la primera vez. Repetir un modulo completado permite practicar y ganar XP por respuestas correctas, pero no duplica el bonus. El multiplicador de XP lo decide el backend leyendo `profiles.plan`.

### GET /api/billing/me

Devuelve el plan actual y beneficios.

```bash
curl -H "Authorization: Bearer <token>" http://localhost:5000/api/billing/me
```

### POST /api/billing/subscribe

Crea una suscripcion Mercado Pago para Nivela Plus desde backend y devuelve solo la URL de checkout.

```bash
curl -X POST http://localhost:5000/api/billing/subscribe \
  -H "Authorization: Bearer <token>"
```

### POST /api/billing/cancel

Solicita cancelar la suscripcion en Mercado Pago y sincroniza el estado real con backend.

```bash
curl -X POST http://localhost:5000/api/billing/cancel \
  -H "Authorization: Bearer <token>"
```

### POST /api/billing/webhook

Endpoint publico para Mercado Pago. Valida `x-signature`/`x-request-id`, consulta la suscripcion real en Mercado Pago y sincroniza `user_subscriptions` + `profiles.plan`.

Variables requeridas para billing:

```env
MERCADO_PAGO_ACCESS_TOKEN=
MERCADO_PAGO_PLUS_PLAN_ID=
MERCADO_PAGO_WEBHOOK_SECRET=
FRONTEND_URL=
```

## Arquitectura Supabase

`config/supabase.py` separa dos clientes:

- `supabase_auth`: usa `SUPABASE_KEY` para validar `Authorization: Bearer <supabase_access_token>` mediante Supabase Auth.
- `supabase_admin`: se crea de forma lazy con `SUPABASE_SERVICE_ROLE_KEY` para operar sobre `public.profiles` desde Flask despues de validar identidad.

RLS permanece activado. La Service Role Key evita que Flask quede bloqueado por policies de usuario al crear perfiles, sin darle privilegios administrativos al frontend.

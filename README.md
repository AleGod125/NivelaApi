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

## Arquitectura Supabase

`config/supabase.py` separa dos clientes:

- `supabase_auth`: usa `SUPABASE_KEY` para validar `Authorization: Bearer <supabase_access_token>` mediante Supabase Auth.
- `supabase_admin`: se crea de forma lazy con `SUPABASE_SERVICE_ROLE_KEY` para operar sobre `public.profiles` desde Flask despues de validar identidad.

RLS permanece activado. La Service Role Key evita que Flask quede bloqueado por policies de usuario al crear perfiles, sin darle privilegios administrativos al frontend.

# Nivela API

API inicial de Nivela construida con Flask, Python y Supabase.

Supabase Auth maneja la autenticación con email/password, Google OAuth y teléfono + OTP. Esta API no almacena contraseñas, códigos OTP, tokens de Google ni datos sensibles de `auth.users`.

## Instalación

```bash
pip install -r requirements.txt
```

## Variables de entorno

Debe existir un archivo `.env` en `backend/`:

```env
SUPABASE_URL=
SUPABASE_KEY=
ALLOWED_ORIGINS=http://localhost:4200
```

`SUPABASE_KEY` debe ser la publishable key para operaciones normales desde el backend. Si más adelante una operación necesita privilegios administrativos, utiliza una variable separada como `SUPABASE_SERVICE_ROLE_KEY` y nunca la expongas en Angular.

## Ejecución

Desde la carpeta `backend/`:

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

Response:

```json
{
  "success": true,
  "message": "Nivela API funcionando"
}
```

### GET /api/users

Devuelve perfiles existentes en `public.profiles`. No devuelve información sensible de `auth.users`.

Response:

```json
{
  "success": true,
  "users": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "username": "alejandro",
      "full_name": "Alejandro Navarro",
      "avatar_url": null,
      "created_at": "2026-08-06T17:00:00+00:00",
      "updated_at": "2026-08-06T17:00:00+00:00"
    }
  ]
}
```

### GET /api/users/<user_id>

Response:

```json
{
  "success": true,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "alejandro",
    "full_name": "Alejandro Navarro",
    "avatar_url": null,
    "created_at": "2026-08-06T17:00:00+00:00",
    "updated_at": "2026-08-06T17:00:00+00:00"
  }
}
```

Si no existe:

```json
{
  "success": false,
  "error": "Usuario no encontrado"
}
```

### POST /api/users

Crea el perfil de Nivela para un usuario ya autenticado en Supabase. La operación es idempotente: si el perfil existe, devuelve el perfil existente.

Request:

```http
Authorization: Bearer <supabase_access_token>
Content-Type: application/json
```

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

Ya existía:

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

## Arquitectura

```text
backend/
├── app.py
├── config/
│   └── supabase.py
├── routes/
│   └── users.py
└── services/
    └── user_service.py
```

La API está preparada para recibir `Authorization: Bearer <supabase_access_token>` y validar la identidad con Supabase antes de crear perfiles.

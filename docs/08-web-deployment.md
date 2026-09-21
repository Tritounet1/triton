# Déploiement web autonome

Le profil `web` expose uniquement le chat, les conversations et les outils réseau. Il ne donne pas accès aux fichiers, commandes shell, projets locaux, clés configurables depuis l’interface, MCP ni tâches de fond.

## Préparer le serveur

Clonez Triton sur le VPS, installez `uv` et `pnpm`, puis construisez le client :

```sh
cd app-desktop
VITE_TRITON_DEPLOYMENT_PROFILE=web pnpm install --frozen-lockfile
VITE_TRITON_DEPLOYMENT_PROFILE=web pnpm build
```

Créez un fichier d’environnement lisible seulement par le compte de service, par exemple `/etc/triton/web.env` :

```dotenv
TRITON_DEPLOYMENT_PROFILE=web
TRITON_DATA_DIR=/var/lib/triton
TRITON_WEB_USERNAME=admin
TRITON_WEB_PASSWORD=replace-with-a-long-password
TRITON_WEB_SESSION_SECRET=replace-with-a-random-48-byte-secret
OPEN_ROUTER_API_KEY=replace-with-the-server-key
```

Générez le secret de session avec `openssl rand -base64 48`. Ne réutilisez jamais les clés du poste desktop. `TRITON_DATA_DIR` doit être un volume persistant, accessible uniquement au compte qui lance Triton.

Lancez ensuite l’API derrière le proxy, sans l’exposer directement :

```sh
set -a; . /etc/triton/web.env; set +a
uv run uvicorn server:app --host 127.0.0.1 --port 8000
```

Le build React est servi par cette API. Une absence de `app-desktop/dist/index.html` renvoie une erreur explicite au lieu de démarrer un site incomplet.

## HTTPS avec Caddy

Utilisez un nom de domaine qui pointe vers le VPS, puis ajoutez :

```caddyfile
triton.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy obtient et renouvelle le certificat TLS. Le cookie de session est marqué `Secure` dans le profil web : HTTPS est donc requis. Gardez Uvicorn sur `127.0.0.1`, activez le pare-feu du VPS et ne rendez publics que les ports 80 et 443.

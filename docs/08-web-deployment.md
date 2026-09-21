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
TRITON_WEB_SECURE_COOKIES=true
OPEN_ROUTER_API_KEY=replace-with-the-server-key
```

Générez le secret de session avec `openssl rand -base64 48`. Ne réutilisez jamais les clés du poste desktop. `TRITON_DATA_DIR` doit être un volume persistant, accessible uniquement au compte qui lance Triton.

Lancez ensuite l’API :

```sh
set -a; . /etc/triton/web.env; set +a
uv run uvicorn server:app --host 0.0.0.0 --port 8000
```

Le build React est servi par cette API. Une absence de `app-desktop/dist/index.html` renvoie une erreur explicite au lieu de démarrer un site incomplet.

## Docker Compose

Le dépôt fournit `Dockerfile` et `docker-compose.yml`. Ils construisent le client React dans l’image, lancent FastAPI avec un utilisateur non privilégié et conservent les données dans le volume Docker `triton-data`. Le conteneur expose son port 8000 pour que Dokploy puisse le relier à son domaine et à son HTTPS.

Pour tester localement, sans installer Python ni Node :

```sh
cp .env.example .env
```

Remplacez `TRITON_WEB_PASSWORD`, `TRITON_WEB_SESSION_SECRET` et `OPEN_ROUTER_API_KEY`, puis mettez `TRITON_WEB_SECURE_COOKIES=false` pour le test HTTP local. Lancez ensuite :

```sh
docker compose up --build -d
```

Ouvrez `http://127.0.0.1:8000`. Le port est limité à la machine hôte.

Pour Dokploy, déployez ce dépôt avec Docker Compose, configurez le domaine et HTTPS dans Dokploy, puis renseignez les mêmes variables d’environnement dans son interface. Gardez `TRITON_WEB_SECURE_COOKIES=true`, qui est la valeur par défaut, pour que la session ne soit transmise qu’en HTTPS.

## Limites et observabilité

Le profil web limite par défaut chaque client à 120 requêtes par minute et refuse les requêtes de plus de 12 Mio. Ajustez `TRITON_WEB_RATE_LIMIT_REQUESTS`, `TRITON_WEB_RATE_LIMIT_WINDOW_SECONDS` et `TRITON_WEB_MAX_REQUEST_BYTES` dans Dokploy si nécessaire. Les requêtes web sont écrites au format JSON dans les logs Docker, avec la méthode, la route, le statut et la durée, sans contenu de conversation.

```sh
docker compose logs -f triton
docker compose exec triton python -m triton.logs_summary
```

Le second affichage résume les appels, tokens, outils et coûts enregistrés dans le volume persistant.

## Sauvegarde du volume

Créez une archive depuis la machine qui héberge Docker :

```sh
mkdir -p backups
docker compose exec -T triton tar -C /data -czf - . > backups/triton-data.tar.gz
```

Pour restaurer, arrêtez le service, videz le volume puis réinjectez l’archive :

```sh
docker compose down
docker compose run --rm --no-deps triton sh -c 'rm -rf /data/*'
cat backups/triton-data.tar.gz | docker compose run --rm -T --no-deps triton tar -C /data -xzf -
docker compose up -d
```

Conservez les archives dans un stockage chiffré et distinct du VPS.

# Fluxo de deploy

1. **Admin** envia um funil (`.zip` com HTML/CSS/JS/PHP ou um app Node.js) em
   `/admin/funis`. O sistema extrai para `instance/funnels/<slug>/` e detecta
   automaticamente a stack (`Funnel.stack`: `static` | `php` | `node`) — a
   presença de um `package.json` (na raiz ou uma pasta abaixo) implica `node`;
   senão, qualquer `*.php` implica `php`; senão, `static`. Para `node`,
   `Funnel.app_root` guarda o diretório do `package.json` e `Funnel.entry_file`
   o arquivo de entrada resolvido (`scripts.start`, `main`, ou candidatos como
   `server.js`/`app.js`/`index.js`) — vazio quando só `npm start` resolve.
   `node_modules` do zip é sempre descartado: é recompilado no VPS (`npm ci`),
   pois pode conter binários nativos (ex.: `better-sqlite3`) montados para o SO
   errado.
2. **Usuário** cadastra credenciais de provedores em `/credenciais` (VPS e/ou
   registrador — chaves de API próprias do usuário, criptografadas em repouso
   com Fernet).
3. **Usuário** compra um VPS em `/vps` (`jobs.start_vps_purchase_job`):
   cria a instância via API do provedor, aguarda IP/boot, instala nginx +
   certbot via SSH (`services/deploy/provisioner.py`).
4. **Usuário** abre um funil em `/funis/<id>` e informa: VPS de destino,
   registrador (para domínios novos), quantidade N e os N nomes de domínio
   (um por linha). Isso cria um `DeployBatch` com N `Deployment`s.
5. `jobs.start_deploy_batch_job` roda cada deployment em sequência
   (`jobs._run_single_deployment`), passando pelos estados:
   `registering_domain → dns → uploading → nginx → ssl → live`. Funis `node`
   passam por dois estados extras entre `uploading` e `nginx`:
   `installing` (`npm ci`/`npm install`, e `npm run build` se houver script
   `build` e nenhum `dist/`/`build/` já presente no zip) e `starting` (grava
   `.env`, cria/(re)inicia a unit systemd `funil-<domínio>.service` e só segue
   depois que a app responder em `http://127.0.0.1:<porta>/`). A porta é
   alocada por VPS (`services/deploy/ports.allocate_port`, 3001–3999) e fica
   salva em `Deployment.app_port`.
   Cada etapa é logada em `instance/deploy_logs/<deployment_id>.log` e
   transmitida ao vivo via WebSocket (`/deploys/ws?id=<id>&token=<api_key>`).

   Para funis `node`, um redeploy (inclusive "Tentar novamente") preserva
   `*.db`, `*.sqlite*` e `.env` que já existirem no webroot — copiados para
   `/var/lib/funis/<domínio>/` antes do upload e restaurados por cima depois
   (`deployer._snapshot_persistent_state` / `_restore_persistent_state`). Isso
   existe porque a chave da ProsperidadePay é configurada no próprio painel
   admin do funil (fica salva no SQLite do site) — sem essa preservação, um
   retry apagaria a configuração de pagamento junto com o histórico de
   transações.
6. O **dashboard** e a página `/vps` mostram, por VPS, quantos deploys estão
   com `status == "live"` (`Vps.deployment_count`). Não há limite — o próprio
   usuário decide quantos funis/domínios ficam em cada VPS.
7. **Remover** um deploy (`/deploys/<id>/remover`) apaga o site do nginx, a
   unit systemd (se existir — inofensivo tentar remover em funis não-node),
   os arquivos no VPS e o estado persistido em `/var/lib/funis/<domínio>/`, e
   remove o registro `Deployment`.

## Modo mock (testes locais sem custo)

Credenciais com `provider = "mock"` (tanto para VPS quanto para registrador)
simulam todo o fluxo sem chamadas de API reais nem SSH real — úteis para
testar o pipeline fim-a-fim localmente antes de usar provedores reais.

## Reconexão após reinício

Como os jobs rodam em threads dentro do processo Flask (sem Celery/Redis),
um reinício do servidor mata qualquer job em andamento. `app/__init__.py`
varre, na inicialização, VPS/Deployments/DeployBatches presos em estados não
terminais e os marca como erro — evitando que fiquem "travados" para sempre.
Deploys podem ser reenviados manualmente pelo botão "Tentar novamente".

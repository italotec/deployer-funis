# Fluxo de deploy

1. **Admin** envia um funil (`.zip` com HTML/CSS/JS/PHP) em `/admin/funis`. O
   sistema extrai para `instance/funnels/<slug>/` e detecta automaticamente se
   há PHP (`Funnel.has_php`).
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
   `registering_domain → dns → uploading → nginx → ssl → live`.
   Cada etapa é logada em `instance/deploy_logs/<deployment_id>.log` e
   transmitida ao vivo via WebSocket (`/deploys/ws?id=<id>&token=<api_key>`).
6. O **dashboard** e a página `/vps` mostram, por VPS, quantos deploys estão
   com `status == "live"` (`Vps.deployment_count`). Não há limite — o próprio
   usuário decide quantos funis/domínios ficam em cada VPS.
7. **Remover** um deploy (`/deploys/<id>/remover`) apaga o site do nginx e os
   arquivos no VPS, e remove o registro `Deployment`.

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

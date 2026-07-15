# Porkbun (não implementado — stub)

Registrador mainstream com API moderna e barata — **não** é DMCA-resistente
(segue políticas de abuso padrão dos EUA), mas é uma ótima opção "normal"
para complementar Namecheap/Njalla quando o domínio não precisa de anonimato.

## API

REST/JSON, base `https://api.porkbun.com/api/json/v3` (atenção: em 2025 o
host mudou de `porkbun.com` para `api.porkbun.com` — usar sempre o novo).

- Autenticação: header `X-API-Key` / `X-Secret-API-Key`, ou `apikey` /
  `secretapikey` no corpo JSON.
- Checar disponibilidade/registrar: `GET /domain/getRegistrationRequirements/{tld}`
  primeiro (nem todo TLD é registrável via API), depois o endpoint de
  registro.
- Criar registro DNS: `POST /dns/create/{domain}` com `type`, `content`
  (tipos suportados: A, MX, CNAME, ALIAS, TXT, NS, AAAA, SRV, TLSA, CAA,
  HTTPS, SVCB) — ao contrário da Namecheap, este é um **add**, não substitui
  os registros existentes.

## Para implementar

Seguir o padrão de `app/services/registrar/njalla.py` (JSON simples, sem o
parsing XML que a Namecheap exige) — deve ser o mais rápido de adicionar
dos providers ainda não implementados.

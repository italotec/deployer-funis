# Njalla (implementado)

Implementação: `app/services/registrar/njalla.py`. API JSON-RPC própria em
`https://njal.la/api/1/`, autenticação via header
`Authorization: Njalla <api_token>`.

## Credenciais necessárias

- `api_token` — gerado em Njalla → Account → API. Pode ser restringido por
  IP/domínio/método na própria Njalla (recomendado restringir aos métodos
  usados por este app: `find-domains`, `register-domain`, `add-record`,
  `get-domain`).

## Por que a Njalla é a opção "no-DMCA" mais forte

A Njalla é projetada para privacidade do titular: o domínio é registrado em
nome da própria Njalla por procuração, então o WHOIS nunca expõe o dono
real. Isso soma-se à postura conhecida de resistência a notificações DMCA.

## Comportamento assíncrono do registro

`register-domain` retorna um `task` (não confirma o registro na hora). Este
app assume sucesso otimista e marca o `Domain.status = "registered"`
imediatamente após a chamada — para maior robustez, seria possível fazer
polling de `get-domain` (método `get_status()` já exposto no provider) até o
domínio realmente aparecer como ativo antes de prosseguir para a etapa de
DNS. Considerar isso se surgirem falhas de "registro não veio a tempo" no
fluxo de deploy.

## Saldo pré-pago

A Njalla funciona com carteira pré-paga (`Wallet.get_balance()` na API,
ainda não exposta por este provider). Se o saldo for insuficiente,
`register-domain` deve retornar um erro — capturado e propagado como
exceção por `_call()`, aparecendo no log do deploy.

## VPS Njalla

A Njalla também vende servidores com uma API real e bem documentada — ver
[`docs/providers/vps/njalla-vps.md`](../vps/njalla-vps.md), forte candidata
a próximo provider de VPS a implementar.

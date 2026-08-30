# Contabo (implementado)

Implementação: `app/services/vps/contabo.py`.

## Autenticação

OAuth2 `grant_type=password` contra
`https://auth.contabo.com/auth/realms/contabo/protocol/openid-connect/token`,
usando 4 campos que o usuário obtém no Customer Control Panel da Contabo:

- `client_id`
- `client_secret`
- `api_user` (e-mail da API)
- `api_password`

Esses campos são o que o usuário preenche em **Credenciais → VPS → Contabo**.

**Causa mais comum de `401 Unauthorized` nesse endpoint:** `api_password` precisa ser a
*API password* gerada especificamente no painel Contabo (Customer Control Panel → API), e não a
senha de login da conta. Use o botão "Testar" na página de Credenciais para validar as 4 chaves
antes de tentar criar uma instância.

## Criação de instância

`POST /v1/compute/instances` — o provider gera um par de chaves SSH RSA
localmente, envia a pública via `POST /v1/secrets` (`type: "ssh"`) e referencia
o `secretId` retornado em `sshKeys`. A chave privada fica guardada
(criptografada com Fernet) em `Vps.ssh_key_enc` para as próximas conexões SSH.
Se `POST /v1/compute/instances` falhar, o secret recém-criado é removido
(`DELETE /v1/secrets/{id}`, best-effort) para não acumular chaves órfãs a cada
tentativa.

O `imageId` do Ubuntu 22.04 é resolvido em tempo real via
`GET /v1/compute/images` (`_resolve_ubuntu_image_id`), casando pelo nome —
`DEFAULT_UBUNTU_IMAGE_ID` só é usado como fallback se essa consulta falhar.

## Erros

Toda chamada HTTP passa por `ContaboProvider._request`, que levanta
`RuntimeError` com a mensagem e o `requestId` retornados pelo corpo da
resposta da Contabo (`{"message": "...", "requestId": "..."}`), em vez do
`400 Client Error: Bad Request for url: ...` genérico do
`requests.raise_for_status()`. Esse `requestId` é o que o suporte da Contabo
pede para investigar um pedido específico.

## Diagnóstico

`scripts/contabo_check.py` faz só chamadas de leitura (auth, `GET
/compute/images`, `GET /compute/instances`) usando uma credencial já salva —
não cria instância nem gasta nada. Útil para confirmar se `DEFAULT_UBUNTU_IMAGE_ID`
ainda existe no catálogo e se os `productId`/`region` configurados batem com a conta:

```
python scripts/contabo_check.py [--credential-id N]
```

## Histórico: catálogo `V91`/`V92`/`V93` descontinuado (2026-08)

A Contabo aposentou a linha antiga de Cloud VPS (`V91`, `V92`, `V93`) para
**novos pedidos** — `POST /v1/compute/instances` passou a responder `400`
com `"No offer was found for product ID 'V91' and period '1'"`, mesmo em
contas que já têm instâncias antigas rodando nesses ids (apenas
grandfathered; a Contabo continua listando-as em `GET /compute/instances`,
o que confundia o diagnóstico). O catálogo atual é a série `V153`-`V158`
("Cloud VPS 4" a "Cloud VPS 18", todas SSD) — já atualizado em `PLANS`.
Existe também uma linha NVMe "Plus" (`V159`-`V164`) não incluída em `PLANS`
por ora.

## Pontos que exigem verificação periódica

A API da Contabo evolui; antes de usar em produção, revalide no painel/documentação oficial:

- **`productId`** (planos): os valores em `PLANS` podem mudar de
  nome/disponibilidade por região — a Contabo já fez isso ao menos uma vez
  (ver histórico acima). Não há endpoint de leitura para listar todos os
  productId/period vendáveis sem já ter uma instância; a única forma
  confiável de validar é tentar `POST /compute/instances` (o que compra) ou
  conferir a documentação/painel oficial.
- **Regiões** (`REGIONS`): confirme a lista atual de regiões disponíveis para
  a conta do usuário.

## Preço

A API não expõe preço por plano de forma simples; os valores em `list_plans()`
são apenas rótulos — o usuário deve confirmar o custo no painel da Contabo
antes de comprar.

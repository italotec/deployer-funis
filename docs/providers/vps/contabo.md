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

## Pontos que exigem verificação periódica

A API da Contabo evolui; antes de usar em produção, revalide no painel/documentação oficial:

- **`productId`** (planos): os valores em `PLANS` (`V91`, `V92`, `V93`) podem
  mudar de nome/disponibilidade por região.
- **`imageId`** padrão do Ubuntu 22.04 (`DEFAULT_UBUNTU_IMAGE_ID`): se a
  Contabo descontinuar essa imagem, `create_instance` falhará — nesse caso
  liste imagens via `GET /v1/compute/images` e atualize a constante.
- **Regiões** (`REGIONS`): confirme a lista atual de regiões disponíveis para
  a conta do usuário.

## Preço

A API não expõe preço por plano de forma simples; os valores em `list_plans()`
são apenas rótulos — o usuário deve confirmar o custo no painel da Contabo
antes de comprar.

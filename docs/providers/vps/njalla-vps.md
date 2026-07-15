# Njalla VPS (candidato forte para promoção a "first-class")

**Ainda não implementado como `VpsProvider`**, mas diferente dos outros
provedores offshore desta pasta, a Njalla **tem uma API real e bem definida**
para servidores — não só para domínios. Isso a torna a opção que melhor
combina os dois requisitos originais do projeto ("tem API" + "não segue
DMCA"). Vale promovê-la a provider first-class antes dos outros desta pasta.

## Evidência da API (verificada em código-fonte público)

Mesmo endpoint JSON-RPC usado pelo registrador (`https://njal.la/api/1/`,
header `Authorization: Njalla <token>`), com métodos dedicados a servidores:

- `add-server(name, type_, os_, ssh_key, months, autorenew)` — cria o servidor
- `list-servers()` / `get-server(id)` — lista/consulta
- `list-server-types()` / `list-server-images()` — planos e imagens disponíveis
- `start-server(id)` / `stop-server(id)` / `restart-server(id)`
- `reset-server(id, os_, ssh_key, type_)` — reinstala o SO
- `remove-server(id)`, `renew-server(id, months)`

Isso mapeia quase 1:1 para a interface `VpsProvider` já usada neste projeto
(`app/services/vps/base.py`): `list_plans` ≈ `list-server-types`,
`list_regions` (a Njalla não expõe região separadamente — verificar se algum
tipo de servidor já embute a região), `create_instance` ≈ `add-server`,
`get_instance` ≈ `get-server`, `destroy` ≈ `remove-server`.

## Antes de implementar

- Confirmar o schema exato de resposta de `add-server` (contém IP? ou é
  necessário um `get-server` subsequente até o servidor ficar pronto?).
- Confirmar como a chave SSH pública é passada (`ssh_key` parece ser a chave
  pública diretamente, sem endpoint de "secrets" separado como na Contabo).
- Confirmar preços e disponibilidade de planos — a Njalla cobra da carteira
  pré-paga do usuário (`Wallet.get_balance()`), então a compra pode falhar
  silenciosamente por saldo insuficiente; tratar esse erro explicitamente.

## Referência de implementação

O pacote Python `Njalla` (`Njalla/Server.py` e `Njalla/API.py` no GitHub) é um
bom guia de referência para os nomes exatos de parâmetros. O registrador
Njalla já implementado em `app/services/registrar/njalla.py` reutiliza o
mesmo padrão de autenticação — um novo `app/services/vps/njalla.py` pode
copiar `_headers`/`_call` dali quase sem alteração.

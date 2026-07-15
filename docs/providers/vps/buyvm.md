# BuyVM / Frantech (não implementado — stub)

Frantech opera com política de abuso relativamente permissiva e é uma escolha
comum na comunidade offshore/DMCA-resistant (não é "ignora tudo", mas é bem
mais tolerante que Hetzner/DO/Vultr).

## API

Painel de controle próprio chamado **Stallion**. Segundo a wiki oficial
(`wiki.buyvm.net/doku.php/stallion`):

- A API é **compatível com SolusVM** (útil se já existir tooling SolusVM).
- Cobre operações básicas: iniciar/parar/reiniciar a instância, status,
  configuração de IP/rDNS, snapshots, deploy a partir de templates de SO.
- É descrita pela própria BuyVM como "muito básica" — antes de implementar,
  confirmar se existe endpoint de **criação** de instância via API (a doc
  pública enfatiza gerenciamento de instâncias já existentes; compra/criação
  pode exigir passar pelo client area em vez de API pura).

## Antes de implementar

- Ler `https://wiki.buyvm.net/doku.php/stallion` (seção "Client API") para o
  schema exato de autenticação e endpoints.
- Confirmar se `create_instance` (compra de uma nova Slice) é possível via
  API ou se essa etapa continua manual no client area — isso mudaria o
  encaixe no fluxo "usuário compra VPS pelo app" do restante da plataforma.

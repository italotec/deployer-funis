# Namecheap (implementado)

Implementação: `app/services/registrar/namecheap.py`. API XML clássica da
Namecheap (`namecheap.domains.*`).

## Credenciais necessárias

- `api_user` — usuário da API (pode ser igual ao login, mas precisa estar
  habilitado em Namecheap → Profile → Tools → API Access).
- `api_key` — chave gerada no mesmo painel.
- `client_ip` — **obrigatório**: a Namecheap só aceita chamadas vindas de um
  IP previamente cadastrado (whitelist) nas configurações de API access.
  Deve ser o IP público do servidor onde este app roda.
- `contact` (sub-objeto) — dados de contato (nome, endereço, telefone,
  e-mail) exigidos pela ICANN para registrar um domínio. Preenchidos no
  formulário de credenciais em "Dados de contato".
- `sandbox` (opcional, `"1"`) — usa `api.sandbox.namecheap.com` para testes
  sem gastar dinheiro real (exige conta sandbox separada).

## Pontos de atenção

- `namecheap.domains.create` cobra automaticamente na conta Namecheap do
  usuário — não há passo de "confirmação" adicional.
- A resposta é XML; qualquer mudança de schema pela Namecheap quebra o parser
  em `_call()`. Revalidar contra `https://www.namecheap.com/support/api/methods/`
  se `register()`/`check_availability()` começarem a falhar.
- `set_dns_a` usa `domains.dns.setHosts`, que **substitui todos os registros
  DNS existentes do domínio** pelos informados na chamada — não é um "add",
  é um "replace". Se o domínio já tiver outros registros (MX, TXT etc.) que
  precisem ser preservados, a implementação atual os apaga. Ajustar para
  primeiro ler os hosts existentes (`domains.dns.getHosts`) e mesclar, se
  isso for um problema no uso real.

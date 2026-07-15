# Epik (não implementado — stub)

Registrador conhecido por atrair clientes de plataformas com moderação mais
pesada (ex.: hospedou domínios de Parler, Gab). Não é formalmente
"DMCA-ignore", mas tem histórico de maior tolerância a conteúdo controverso
que registradores mainstream — avaliar caso a caso, não é garantia legal.

## API

Documentação completa em `https://docs.userapi.epik.com/v2/`. Pontos-chave:

- Autenticação exige **assinatura válida + IP whitelisting** (mais estrita
  que Namecheap/Porkbun — checar o processo exato de assinatura de request
  na doc antes de implementar).
- Cobre registro, renovação, transferência, WHOIS e gerenciamento de DNS.
- **Não é adequado para "drop-catch"** (captura de domínios expirando) — não
  é uma limitação relevante para o caso de uso deste projeto (registro de
  domínios novos), mas documentado aqui por transparência.

## Para implementar

Seguir o padrão de `RegistrarProvider` (`check_availability`, `register`,
`set_dns_a`). Como a autenticação exige assinatura de request (não é só
header estático como os outros três providers), vale isolar essa lógica em
um método privado `_sign_request()` dedicado.

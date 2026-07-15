# FlokiNET (não implementado — stub)

Provedor islandês/romeno/finlandês focado em privacidade e resistência a
DMCA por jurisdição (opera sob leis da Islândia/Romênia, fora do alcance
direto de notificações DMCA dos EUA). Sem exigência de dados pessoais para
criar conta; aceita pagamento em criptomoedas.

## API

Não há evidência de uma API pública de provisionamento automatizado —
segundo a documentação e reviews disponíveis, o provisionamento é manual
via client area (WHMCS-like), sem uma API de criação de servidor por
enquanto. Como o requisito do projeto é "provedor com API", a FlokiNET
**não se qualifica hoje** para virar um `VpsProvider` automatizado — só
serviria como VPS comprado manualmente e cadastrado "à mão" no app (sem
`create_instance` automático).

## Reavaliar no futuro

Se a FlokiNET lançar uma API de reseller/provisionamento, este stub deve ser
promovido a implementação real seguindo o mesmo padrão de
`app/services/vps/contabo.py`.

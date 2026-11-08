# surebet-monitor

Teste de 7 dias com banca **virtual** de R$ 1.000 para responder uma pergunta: os gaps de surebet
(arbitragem entre casas) aparecem com frequência, margem e duração suficientes para valer a pena?

Nenhuma aposta real é feita. O sistema só lê odds, simula e registra.

## Como funciona

A cada 30 minutos (GitHub Actions):

1. **Leitura**: busca odds de pré-jogo na [The Odds API](https://the-odds-api.com) para os esportes configurados
   (mercados `h2h` 1x2/moneyline e `totals` over/under).
2. **Detecção**: em cada mercado, pega a melhor odd de cada resultado entre todas as casas.
   Se `soma(1/odd) < 1`, há lucro garantido: `margem = 1/soma - 1`.
   - descarta odds com mais de 15 min sem atualização;
   - aplica comissão de 5% nas exchanges (Betfair, Matchbook, Smarkets);
   - margem acima de 8% ou todas as pernas na mesma casa = **suspeita** (quase sempre erro de odd): registra, não aposta.
3. **Aposta virtual**: 10% da banca por gap (teto R$ 150, mínimo R$ 20), dividido entre os resultados para retorno igual
   e arredondado para reais inteiros, como seria numa aposta real. Uma aposta por mercado/jogo.
4. **Persistência**: na leitura seguinte, verifica se o mesmo gap (mesmas casas) ainda existe. Esse é o teste de
   realidade: gap que some em menos de 30 min dificilmente seria executado à mão.
5. **Liquidação**: 3h após o início do jogo busca o placar real e paga a perna vencedora.
6. **Relatório**: `REPORT.md` com banca, lucro realizado, cenário conservador (só gaps que persistiram),
   frequência por esporte/casa/mercado, margem e duração dos gaps.

## Colocar para rodar

1. Criar conta na The Odds API. O plano gratuito (500 créditos/mês) **não é suficiente**: a configuração padrão gasta
   ~32 créditos por leitura (8 esportes x 2 regiões x 2 mercados), cerca de 11 mil na semana.
   O plano de 20 mil créditos atende com folga.
2. No GitHub do repositório, em *Settings > Secrets and variables > Actions*:
   - Secret `ODDS_API_KEY` = chave da API
   - Variable `SUREBET_ENABLED` = `true`
   - Opcionais: `SUREBET_SPORTS`, `SUREBET_REGIONS`, `SUREBET_MARKETS` (listas separadas por vírgula)
3. Fazer merge deste branch no `main` (agendamentos do GitHub Actions só rodam no branch padrão).
4. Disparar a primeira leitura em *Actions > surebet-monitor > Run workflow*. O teste conta 7 dias a partir dela;
   depois disso só liquida o que estiver aberto.
5. Acompanhar `surebet-monitor/REPORT.md`. Dados brutos: `data/state.json` e `data/sightings.jsonl`
   (cada gap visto, em cada leitura).

Para desligar: variable `SUREBET_ENABLED` = `false`.

## Rodar localmente

```bash
cd surebet-monitor
python -m unittest discover -s tests -t .      # testes
python -m surebet demo                          # simulação offline com dados fictícios
ODDS_API_KEY=... python -m surebet run          # uma leitura real
```

Só usa biblioteca padrão do Python 3.10+.

## Limitações conhecidas (ler antes de tirar conclusão)

- **Casas cobertas**: a The Odds API cobre casas europeias/britânicas (regiões `eu` e `uk`), não as casas licenciadas
  no Brasil (Betano, Superbet, KTO etc.). O teste mede se o fenômeno existe e com que força; para operar no Brasil
  seria preciso uma fonte de odds dessas casas.
- **Intervalo de 30 min**: gaps que abrem e fecham entre duas leituras não são vistos. Reduzir o intervalo aumenta
  o custo de API proporcionalmente.
- **Otimismo da simulação**: assume que todas as pernas seriam aceitas no valor e na odd lidos, sem limite de conta
  e sem cancelamento. Na prática, casas limitam contas que fazem arbitragem e anulam apostas em odds erradas.
  Por isso o relatório separa o cenário conservador.
- Só pré-jogo. Ao vivo os gaps são mais frequentes, mas fecham em segundos.

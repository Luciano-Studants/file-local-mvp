# Objetivos permanentes do Arquivo Local

## Produto e distribuição

- Aplicativo local, inicialmente para Windows 10, operado por menu radial junto ao arquivo selecionado.
- Meta de longo prazo: publicar online uma versão para download **gratuita para uso**, para que usuários de Windows 10 possam utilizá-la no próprio computador.
- “Gratuita para uso” é objetivo do produto; não significa garantia de suporte a toda edição/build do Windows 10, suporte técnico, hospedagem permanente ou aprovação de distribuição. A matriz de versões e canais de release deverá ser definida e testada antes de publicar.
- O projeto deve manter uma licença compatível, avisos de terceiros, hashes/assinatura quando disponíveis, instruções verificáveis e um canal público de distribuição escolhido antes de uma release.

## Escopo de plataforma

- O alvo decidido nesta etapa é Windows, com Windows 10 como requisito de compatibilidade. Linux não faz parte do alvo atual e não deve conduzir decisões ou testes de release sem uma nova decisão explícita.
- Não incluir funcionalidades exclusivas de macOS/iOS nem dependências de Finder, Pages, Keynote, Numbers, iCloud ou APIs Apple.
- Quando houver uma alternativa interoperável para Windows, usar formatos e APIs Windows apropriados; quando não houver alternativa adequada, declarar a função fora de escopo.

## Regras de produto e segurança

- Shift abre ações radiais rápidas por tipo de arquivo; Shift+F9 é reservado para ações globais/secundárias.
- Processamento local como padrão; preservar originais em conversões; não sobrescrever silenciosamente; manter workers descartáveis, staging confinado, timeout e cancelamento.
- Não executar como administrador. Ações destrutivas, como Move, devem ter confirmação explícita e relatório de resultado.
- Não marcar recursos como prontos sem teste real na matriz Windows escolhida, além de testes automatizados e atualização de licenças/avisos.

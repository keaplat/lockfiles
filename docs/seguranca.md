# Formatos e limites

## Arquivos originais

O Cofre Temporal lê somente os itens selecionados. Ele não apaga originais, altera permissões de pastas, se instala na inicialização do Windows ou bloqueia o Explorer. Uma cópia em claro, inclusive na Lixeira ou em um backup, continua acessível fora do cofre.

## Senha

O ZIP usa WinZip AES-256 / AE-2, implementado pelo pyzipper 0.4.0. O conteúdo é criptografado; nomes, estrutura e metadados do ZIP ficam visíveis. A senha não é salva em arquivo nem passada na linha de comando. Não há recuperação de senha esquecida. Prefira uma frase longa e exclusiva.

## Data

O formato é compatível com tlock/age. O programa usa `tle` 1.2.0 e fixa o hash da rede drand quicknet:

```text
52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971
```

A data fica visível no cabeçalho; o ZIP, incluindo seus nomes de arquivos, fica criptografado. A consulta ao relógio local serve para a interface. O bloqueio criptográfico depende das assinaturas verificadas pelo `tle`.

Este modo exige internet nesta versão. A segurança depende da criptografia e de um número suficiente de operadores drand permanecerem honestos. Se a rede deixar de publicar assinaturas antes da rodada escolhida, a recuperação poderá ficar impossível. Consulte os [pressupostos do drand](https://docs.drand.love/docs/timelock-encryption/).

## Integridade e restauração

O programa verifica mudanças de tamanho e data de modificação durante a leitura. Na abertura, as bibliotecas validam a integridade criptográfica. Os arquivos só são publicados no destino quando toda a restauração termina.

A extração recusa caminhos que escapem do destino, nomes reservados do Windows, links e colisões de nomes. O processamento acontece em blocos, com ZIP64 e limite de 200 mil entradas por cofre.

Durante a criação temporal, o ZIP vai diretamente à criptografia, sem um ZIP intermediário em claro. Na restauração, há conteúdo em claro em uma pasta temporária no destino. Falhas e cancelamentos normais removem essa pasta, mas isso não é apagamento seguro. Queda de energia ou encerramento forçado podem deixar temporários `.cofre-*`.

O aplicativo não é um antivírus, não interpreta textos ou imagens e não faz uma restauração completa de teste imediatamente após criar cada cofre. Também não preserva ACLs, fluxos alternativos NTFS ou todos os atributos avançados do sistema de arquivos. O código do aplicativo não passou por auditoria independente.

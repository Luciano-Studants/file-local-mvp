# Modelos de remoção de fundo

Só esta pasta é consultada (ao lado do aplicativo). Nada é baixado pelo aplicativo. Cada arquivo é conferido pelo **SHA-256** antes de carregar; arquivo diferente é recusado.

| Arquivo | Incluído no pacote | Tamanho | SHA-256 |
|---|---|---|---|
| `u2netp.onnx` (leve) | sim | 4 574 861 B | `309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8` |
| `u2net.onnx` (preciso) | não — opcional, coloque aqui | 175 997 641 B | `8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491` |

Origem dos arquivos: release `v0.0.0` do projeto rembg (https://github.com/danielgatis/rembg/releases/tag/v0.0.0), que converteu para ONNX os pesos oficiais do **U²-Net** (Qin et al., Pattern Recognition 2020; https://github.com/xuebinqin/U-2-Net, licença Apache-2.0; cópia em `licenses/U2-Net-Apache-2.0-LICENSE.txt`). Os pesos foram treinados no conjunto DUTS-TR (pesquisa); **os termos desse conjunto não foram revistos juridicamente** (pendência registrada).

O modelo `isnet-general-use` (IS-Net) **não é usado**: foi treinado com o DIS5K, cujos termos de uso permitem só uso não comercial e proíbem redistribuição.

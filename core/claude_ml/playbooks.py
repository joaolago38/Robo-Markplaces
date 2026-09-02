"""
Playbooks Claude × Mercado Livre.

Um playbook por chamada (nunca o catálogo inteiro). Placeholders vêm do JSON
do robô — o modelo não recebe colchetes vazios nem inventa demanda JoomPulse.
"""
from __future__ import annotations

from typing import Any

from core.claude_ml.numeros import cfg_bool, num

_N_INF = "não informado — use só o JSON; se faltar, diga o que falta (n/d)"

# proposito (substring ou id) → playbook. ruptura/guerra ficam só com SYSTEM_* da dosagem.
_MAPA_PROPOSITO: tuple[tuple[str, str], ...] = (
    ("otimizar_listing", "seo_titulo"),
    ("auditor_anuncio", "auditor_anuncio"),
    ("analise_anuncio", "auditor_anuncio"),
    ("monitor_concorrentes", "inteligencia_competitiva"),
    ("analise_loja", "inteligencia_competitiva"),
    ("avaliac", "padroes_avaliacao"),
    ("descoberta", "demanda_alta"),
    ("acetona", "demanda_alta"),
    ("necessidade_manicures", "brechas_nicho"),
    ("brecha", "brechas_nicho"),
    ("masterprint", "viabilidade_nicho"),
    ("viabilidade", "viabilidade_nicho"),
    ("inteligencia_precos", "pricing_faixas"),
    ("pricing_faixa", "pricing_faixas"),
    ("chat_ml", "atendimento_chat"),
    ("resposta_lead", "atendimento_chat"),
    ("atendimento", "atendimento_chat"),
    ("sazonal", "sazonalidade"),
    ("comparativo_anita", "portfolio_ab"),
    ("portfolio_ab", "portfolio_ab"),
    ("montar_kits", "cross_sell"),
    ("cross_sell", "cross_sell"),
    ("kits_impala", "cross_sell"),
    ("intencao", "intencao_compra"),
    ("removedores", "intencao_compra"),
    ("fornecedor", "catalogo_fornecedor"),
    ("posicionamento", "posicionamento"),
    ("diferenci", "diferenciacao"),
    ("relatorio_manha", "analise_vendas"),
    ("analise_vendas", "analise_vendas"),
    ("copy_descricao", "copy_descricao"),
    ("caracteristica", "caracteristica_beneficio"),
    ("beneficio", "caracteristica_beneficio"),
    ("criativo_ads", "criativo_estatico"),
    ("diretor_arte", "criativo_estatico"),
    ("faq", "faq_vende"),
    ("ciclo_meta", "copy_trafego_pago"),
    ("copy_trafego", "copy_trafego_pago"),
    ("roteiro_video", "roteiro_video"),
    ("headline", "headlines"),
    ("reescrever", "editor_anuncio"),
    ("editor_anuncio", "editor_anuncio"),
    ("promocoes", "ofertas_promocoes"),
    ("ofertas_promo", "ofertas_promocoes"),
    ("pos_venda", "pos_venda_whatsapp"),
    ("branding", "branding"),
    ("objecao", "quebra_objecao"),
    ("plano_conteudo", "plano_conteudo"),
    ("comparativo_honesto", "comparativo_honesto"),
    ("roteiro_live", "roteiro_live"),
    ("teste_criativo", "teste_criativo"),
    ("sortimento", "sortimento"),
    ("margem_vendas", "analise_financeira"),
    ("analise_financeira", "analise_financeira"),
    ("expansao", "expansao_portfolio"),
    ("ads_gatilho", "midia_paga"),
    ("midia_paga", "midia_paga"),
    ("catalogo_concorrente", "lacunas_catalogo"),
    ("sem_venda", "estoque_zumbis"),
    ("estoque_zombie", "estoque_zumbis"),
    ("repricing", "pricing_dinamico"),
    ("pricing_dinamico", "pricing_dinamico"),
    ("reposicao", "reposicao"),
    ("sincronizar_estoque", "reposicao"),
    ("relatorio_estrategia", "plano_ataque"),
    ("plano_ataque", "plano_ataque"),
    ("operacao_24h", "diagnostico_operacao"),
    ("diagnostico", "diagnostico_operacao"),
    ("bundle", "bundles"),
    ("auditor_custo", "auditor_custos_ml"),
    ("preditiv", "predicao_vendas"),
    ("crescimento", "plano_90_dias"),
    ("plano_90", "plano_90_dias"),
    ("perfil_comprador", "perfil_comprador"),
    ("conversao_manicures", "perfil_comprador"),
    ("panorama", "panorama_categoria"),
    ("sintese_ml", "panorama_categoria"),
    ("analise_ml", "panorama_categoria"),
)

PLAYBOOKS: dict[str, dict[str, str]] = {
    "demanda_alta": {
        "papel": "analista de mercado sênior especializado no marketplace Mercado Livre Brasil",
        "tarefa": (
            "1) Identifique até 10 produtos na categoria com sinais iniciais de demanda em alta "
            "(só se o JSON tiver termo/SKU/visitas/vendas).\n"
            "2) Para cada um: sinal de demanda, concorrência (baixo/médio/alto), perfil do comprador, faixa de preço.\n"
            "3) Destaque até 3 com melhor relação demanda alta × concorrência baixa."
        ),
        "restricoes": (
            "Priorize o que um vendedor pequeno/médio consegue comprar e enviar. "
            "Sinal fraco = marque. Sem dados = n/d, não complete a tabela com invenção."
        ),
        "formato": (
            "Tabela: Produto | Sinal de demanda | Concorrência | Perfil do comprador | Faixa de preço. "
            "Abaixo: Top 3 pra testar primeiro (1 frase cada)."
        ),
    },
    "inteligencia_competitiva": {
        "papel": "consultor de inteligência competitiva em e-commerce",
        "tarefa": (
            "1) Reconstrua a estratégia dele em 6 dimensões: preço, gama, comprador-alvo, força, fraqueza, como fecha a venda.\n"
            "2) Para cada fraqueza, um ataque específico meu.\n"
            "3) O único movimento que mais o prejudicaria se eu fizesse."
        ),
        "restricoes": "Baseie só no JSON. Separe 'o que dá pra ver' de 'o que estou deduzindo'. Não invente vendas/reputação.",
        "formato": (
            "Tabela de 6 linhas: Dimensão | O que ele faz | Como eu reagiria. "
            "Bloco: Se eu só pudesse fazer UMA coisa: ___ (2 linhas)."
        ),
    },
    "padroes_avaliacao": {
        "papel": "especialista em pesquisa de cliente que lê nas entrelinhas das avaliações",
        "tarefa": (
            "1) Agrupe comentários/perguntas nos 5 padrões de reclamação mais repetidos.\n"
            "2) Impacto na compra: decisivo / incômodo / menor.\n"
            "3) Diferencial exato no meu anúncio, na linguagem do comprador."
        ),
        "restricoes": "Só diferenciais entregáveis. Marque os que exigem mudança na operação. Sem avaliações no JSON = diga o que coletar.",
        "formato": (
            "Tabela: Padrão | Frequência | Impacto na decisão | Meu diferencial. "
            "Linha final: qual reclamação atacar primeiro e por quê."
        ),
    },
    "brechas_nicho": {
        "papel": "estrategista de nicho que encontra espaços vazios em mercados lotados",
        "tarefa": (
            "1) Até 7 brechas (produto, público, formato, serviço) com evidência no JSON.\n"
            "2) Ideia concreta de produto OU ângulo de anúncio.\n"
            "3) Ordene por oportunidade vs. esforço."
        ),
        "restricoes": "Evite 'melhor atendimento' genérico. Conecte a falha observável no JSON.",
        "formato": "Lista 1=melhor: Brecha | Ideia/ângulo | Por que está aberta | Esforço (baixo/médio/alto).",
    },
    "viabilidade_nicho": {
        "papel": "analista de viabilidade que impede queimar dinheiro em nichos ruins",
        "tarefa": (
            "1) Demanda, concorrência, preço/margem, sazonalidade, barreira de entrada.\n"
            "2) Cada fator: verde/amarelo/vermelho + 1 linha.\n"
            "3) 3 riscos específicos. Veredito pode ser NÃO entrar."
        ),
        "restricoes": "Não amenize veredito ruim. Sem dado = amarelo/n/d, não chute verde.",
        "formato": (
            "Tabela: Fator | Nota | Raciocínio. Riscos: 3 itens. "
            "Veredito: ENTRAR / ENTRAR COM CUIDADO / EVITAR + a condição que mudaria a opinião."
        ),
    },
    "pricing_faixas": {
        "papel": "analista de pricing para vendedores de marketplace",
        "tarefa": (
            "1) Organize preços em entrada / intermediária / premium.\n"
            "2) Onde está o volume vs. margem mais saudável.\n"
            "3) Faixa-alvo para novo vendedor e preço de entrada."
        ),
        "restricoes": "Dados fracos demais = diga, não chute faixa.",
        "formato": (
            "Tabela: Faixa | Faixa de preço | Volume | Espaço de margem. "
            "Recomendação: faixa-alvo + preço de entrada + 2 linhas."
        ),
    },
    "perfil_comprador": {
        "papel": "especialista em comportamento do consumidor brasileiro",
        "tarefa": (
            "1) Perfil: quem é, qual trabalho o produto resolve, momento da compra.\n"
            "2) 3 medos na hora de comprar e 3 gatilhos de clique.\n"
            "3) Para cada medo, frase exata de tranquilização no anúncio."
        ),
        "restricoes": "Específico deste produto e faixa de preço. Nada de 'as pessoas querem qualidade'.",
        "formato": "Perfil (parágrafo). Tabela medos→tranquilização (3 linhas). Gatilhos: 3 itens.",
    },
    "sazonalidade": {
        "papel": "analista de sazonalidade do e-commerce brasileiro",
        "tarefa": (
            "1) Meses de pico e queda.\n"
            "2) Mães, Namorados, Pais, Black Friday, Natal, volta às aulas.\n"
            "3) Antecedência de estoque/anúncio conforme prazo de reposição do JSON."
        ),
        "restricoes": "Sem sazonalidade clara na categoria = diga e foque o que de fato move demanda no JSON.",
        "formato": "Calendário: Mês | Demanda esperada | Ação. Bloco: 2 picos mais importantes e quando preparar.",
    },
    "portfolio_ab": {
        "papel": "consultor de portfólio que prioriza lançamentos",
        "tarefa": (
            "1) Compare A e B: demanda, concorrência, margem, logística, risco.\n"
            "2) Nota 1–5 por critério; justifique extremos.\n"
            "3) Vencedor alinhado ao objetivo (margem/volume/reputação) do JSON."
        ),
        "restricoes": "Se vencer no geral mas perder no objetivo, aponte o conflito.",
        "formato": "Tabela: Critério | Produto A | Produto B. Veredito: vencedor + 2 linhas ligadas ao objetivo.",
    },
    "cross_sell": {
        "papel": "especialista em cross-sell e aumento de ticket médio",
        "tarefa": (
            "1) Até 8 complementos que o mesmo comprador levaria junto.\n"
            "2) Kit vs. separado, e por quê.\n"
            "3) 3 com maior ticket e menor esforço."
        ),
        "restricoes": "Lógica real de uso, não só 'mesma categoria'. Preferir SKUs do JSON.",
        "formato": "Tabela: Complementar | Kit ou separado | Por quê. Top 3 para implementar primeiro.",
    },
    "auditor_anuncio": {
        "papel": "auditor de anúncios do Mercado Livre",
        "tarefa": (
            "1) Até 7 diferenças concretas (título, imagens, preço, descrição, prova social, oferta, ficha).\n"
            "2) Ordene da mais importante para a menos.\n"
            "3) Ação específica aplicável hoje em cada uma."
        ),
        "restricoes": "Não diga só 'melhore as fotos' — o quê mudar e por quê. Sem inventar atributo ausente.",
        "formato": "Lista: Diferença | Por que importa | Ação concreta. Bloco: mudança nº1 ainda hoje.",
    },
    "intencao_compra": {
        "papel": "pesquisador de intenção de compra",
        "tarefa": (
            "1) Até 15 perguntas que o comprador faz antes de comprar.\n"
            "2) Trava a compra vs. secundária.\n"
            "3) Quais responder já na descrição."
        ),
        "restricoes": "Pense como comprador desconfiado.",
        "formato": "Tabela: Pergunta | Tipo | Na descrição? (sim/não). Bloco: 5 perguntas que mais aumentam conversão.",
    },
    "catalogo_fornecedor": {
        "papel": "comprador experiente que escolhe o que vale estocar",
        "tarefa": (
            "1) Cada item: demanda Meli, margem, concorrência (só com evidência no JSON).\n"
            "2) Sinalize armadilha (saturado, margem apertada, difícil de enviar).\n"
            "3) Até 3 itens para pedir primeiro + 1 para evitar."
        ),
        "restricoes": "Faltou dado = o que descobrir antes de comprar.",
        "formato": "Tabela: Item | Demanda | Margem | Concorrência | Vale pedir? Top 3 + 1 evitar.",
    },
    "posicionamento": {
        "papel": "estrategista de posicionamento",
        "tarefa": (
            "1) 3 posicionamentos que diferenciam SEM baixar preço.\n"
            "2) Frase de destaque pronta para o anúncio.\n"
            "3) Qual dos 3 é o mais forte neste caso."
        ),
        "restricoes": "Nenhum ângulo pode ser 'mais barato'.",
        "formato": "3× Nome do ângulo | Frase | Pra quem. Recomendação + justificativa.",
    },
    "panorama_categoria": {
        "papel": "analista que resume mercados de forma clara e acionável",
        "tarefa": (
            "1) Panorama: tamanho aparente, players, faixa de preço, o que o cliente valoriza, riscos, maior oportunidade — só com o JSON.\n"
            "2) 1 padrão que a maioria ignora (se visível nos dados).\n"
            "3) Recomendação de entrada: FAZER / NÃO FAZER / OBSERVAR."
        ),
        "restricoes": "Específico desta categoria. Frase que serviria para qualquer nicho = proibida.",
        "formato": "Seções curtas com título. Insight escondido: 1 bloco. Frase: Se eu fosse entrar hoje, eu faria ___.",
    },
    "diferenciacao": {
        "papel": "especialista em diferenciação de produto",
        "tarefa": (
            "1) Até 10 formas (embalagem, brinde, garantia, kit, atendimento, conteúdo, entrega).\n"
            "2) Esforço e impacto na conversão.\n"
            "3) 3 com mais impacto e menos esforço, sem destruir margem (custo no JSON)."
        ),
        "restricoes": "Não sugira diferenciação que zere a margem.",
        "formato": "Tabela: Forma | Esforço | Impacto | Custo extra estimado. Top 3 para começar.",
    },
    "analise_vendas": {
        "papel": "analista de dados de vendas",
        "tarefa": (
            "1) Até 3 campeões e até 3 que drenam atenção sem retorno.\n"
            "2) 1 tendência (sazonal, mix, ticket) visível nos dados.\n"
            "3) Ação nº1."
        ),
        "restricoes": "Só os dados colados no JSON. Faltou série = diga o que falta.",
        "formato": "Campeões | Drenando atenção. Tendência escondida: 1 bloco. Ação nº1: 1 recomendação.",
    },
    "seo_titulo": {
        "papel": "especialista em SEO e títulos do Mercado Livre",
        "tarefa": (
            "1) Até 10 títulos com no máximo 60 caracteres.\n"
            "2) Comece pela palavra de maior busca do JSON; atributos que ranqueiam, sem repetir à toa.\n"
            "3) Marque os 3 mais fortes e por quê."
        ),
        "restricoes": "Máx. 60 caracteres. Sem 'melhor do mundo' nem termos proibidos. Não invente marca/atributo.",
        "formato": "Lista: Título | Nº caracteres. Top 3 + motivo.",
    },
    "copy_descricao": {
        "papel": "copywriter de e-commerce brasileiro especializado em Mercado Livre",
        "tarefa": (
            "1) Descrição: abertura, benefícios (não só ficha), quebra de até 3 objeções, CTA.\n"
            "2) Frases curtas e escaneáveis.\n"
            "3) FAQ curto no fim."
        ),
        "restricoes": "Não invente garantia, prazo ou número ausente do JSON.",
        "formato": "Descrição pronta para colar, em blocos.",
    },
    "caracteristica_beneficio": {
        "papel": "tradutor de característica em benefício",
        "tarefa": (
            "1) Cada característica técnica → benefício que o comprador sente.\n"
            "2) 3 frases prontas para o anúncio.\n"
            "3) Qual benefício é o destaque."
        ),
        "restricoes": "Cada benefício responde 'e daí, o que eu ganho?'.",
        "formato": "Tabela: Característica | Benefício. 3 frases + destaque.",
    },
    "criativo_estatico": {
        "papel": "diretor de arte de performance para anúncios de marketplace e Meta Ads",
        "tarefa": (
            "1) 5 conceitos estáticos: dor, desejo, prova, comparação, antes/depois.\n"
            "2) Ideia da imagem, texto na imagem, por que para o dedo.\n"
            "3) Qual testar primeiro."
        ),
        "restricoes": "Texto na imagem: no máximo 7 palavras por bloco.",
        "formato": "5× Ângulo | Ideia | Texto | Por que para o scroll. Conceito para testar primeiro.",
    },
    "atendimento_chat": {
        "papel": "especialista em atendimento que transforma dúvida em venda",
        "tarefa": (
            "1) Preocupação real por trás da mensagem.\n"
            "2) 2 respostas: formal e próxima/humana.\n"
            "3) Resolver a dúvida e empurrar gentilmente à compra, só com o que o JSON permite oferecer."
        ),
        "restricoes": "Sem tom robótico/defensivo. Não prometa desconto/brinde/troca que não esteja no JSON.",
        "formato": "Preocupação: 1 linha. Resposta 1 (formal) | Resposta 2 (próxima).",
    },
    "faq_vende": {
        "papel": "redator de FAQ que escreve respostas que vendem",
        "tarefa": (
            "1) Até 10 perguntas comuns (JSON + as óbvias do produto, sem inventar spec).\n"
            "2) Resposta curta que reduz medo de comprar.\n"
            "3) 3 que também vão na descrição."
        ),
        "restricoes": "Máx. 3 linhas por resposta. Sem juridiquês.",
        "formato": "Pergunta + Resposta. Bloco: 3 para reaproveitar na descrição.",
    },
    "copy_trafego_pago": {
        "papel": "copywriter de tráfego pago focado no mercado brasileiro",
        "tarefa": (
            "1) 3 textos Facebook: gancho na 1ª linha (dor / curiosidade / prova).\n"
            "2) Corpo curto e CTA.\n"
            "3) Qual testar primeiro."
        ),
        "restricoes": "Tom casual brasileiro. A plataforma Mercado Livre na primeira linha. Sem número inventado.",
        "formato": "3 variações pelo tipo de gancho. Qual testar primeiro + por quê.",
    },
    "roteiro_video": {
        "papel": "roteirista de vídeos curtos que convertem",
        "tarefa": (
            "1) Roteiro 30s pessoa-falando-pra-câmera.\n"
            "2) Gancho 3s, problema, solução, CTA.\n"
            "3) Fala + o que aparece na tela."
        ),
        "restricoes": "Gancho não pode ser 'você sabia que...'. Bater na dor logo.",
        "formato": "Tabela: Tempo | Fala | Texto na tela. 2 ganchos alternativos.",
    },
    "headlines": {
        "papel": "especialista em headlines para criativos de anúncio",
        "tarefa": (
            "1) Até 15 headlines curtas.\n"
            "2) Ângulos: medo, desejo, curiosidade, prova.\n"
            "3) 3 mais fortes para testar."
        ),
        "restricoes": "Máx. 10 palavras. Sem clichê de marketing.",
        "formato": "Listas por ângulo. Top 3 marcadas.",
    },
    "editor_anuncio": {
        "papel": "editor de anúncios do Mercado Livre",
        "tarefa": (
            "1) Reescreva título, abertura, benefícios e CTA mantendo o produto.\n"
            "2) Mantenha o que funciona; conserte o que afasta.\n"
            "3) Explique o que mudou."
        ),
        "restricoes": "Não invente atributos. Títulos ≤ 60 caracteres se gerar título.",
        "formato": "Anúncio novo pronto para colar. 3 bullets do que mudou e por quê.",
    },
    "ofertas_promocoes": {
        "papel": "especialista em ofertas e promoções de e-commerce",
        "tarefa": (
            "1) Até 7 ideias de brinde/bônus/oferta.\n"
            "2) Custo e impacto na decisão.\n"
            "3) Ordene por custo-benefício respeitando custo/margem do JSON."
        ),
        "restricoes": "Nenhuma ideia pode destruir a margem.",
        "formato": "Tabela: Ideia | Custo estimado | Impacto | Custo-benefício. Oferta para começar a testar.",
    },
    "pos_venda_whatsapp": {
        "papel": "especialista em pós-venda e fidelização",
        "tarefa": (
            "1) 3 WhatsApp: após entrega, pedido de avaliação, recompra/complementar.\n"
            "2) Timing de cada uma.\n"
            "3) Tom humano, não automático."
        ),
        "restricoes": "Brasileiro, próximo, sem 'prezado cliente', sem ser invasivo.",
        "formato": "Mensagem 1/2/3 com timing.",
    },
    "branding": {
        "papel": "especialista em branding de e-commerce",
        "tarefa": (
            "1) Até 10 nomes curtos.\n"
            "2) Frase de posicionamento cada.\n"
            "3) 3 mais fortes para o público do JSON."
        ),
        "restricoes": "Fáceis de escrever/pronunciar em português.",
        "formato": "Tabela: Nome | Posicionamento. Top 3 + por quê.",
    },
    "quebra_objecao": {
        "papel": "especialista em vendas e quebra de objeção",
        "tarefa": (
            "1) Até 7 formas de justificar preço mais alto (valor, não desconto).\n"
            "2) Frase pronta para descrição e atendimento.\n"
            "3) Argumento mais convincente neste produto."
        ),
        "restricoes": "Nenhum argumento é baixar preço ou dar desconto.",
        "formato": "Argumento | Frase pronta. Bloco: o mais forte.",
    },
    "plano_conteudo": {
        "papel": "estrategista de conteúdo para e-commerce",
        "tarefa": (
            "1) 10 posts: educativo, prova social, bastidores, oferta.\n"
            "2) Ideia + primeira linha (gancho).\n"
            "3) 3 com maior potencial de comprador novo."
        ),
        "restricoes": "Nada de 'bom dia'. Cada post com objetivo.",
        "formato": "Tabela: Post | Tipo | Gancho. Top 3.",
    },
    "comparativo_honesto": {
        "papel": "redator persuasivo e honesto",
        "tarefa": (
            "1) Tabela comparativa honesta para o anúncio.\n"
            "2) Destaque onde eu ganho; não minta onde perco.\n"
            "3) Frase que reposiciona a desvantagem."
        ),
        "restricoes": "Sem afirmação falsa. Honestidade = credibilidade.",
        "formato": "Critério | Meu produto | Concorrente. Frase de fechamento.",
    },
    "roteiro_live": {
        "papel": "roteirista de live de vendas",
        "tarefa": (
            "1) Abertura, 3 blocos de benefício, oferta, fechamento com urgência.\n"
            "2) Distribua o tempo.\n"
            "3) 3 frases de retenção se a audiência cair."
        ),
        "restricoes": "Oferta só depois de demonstrar valor. Sem número/garantia inventada.",
        "formato": "Roteiro por blocos com tempo. 3 frases de retenção.",
    },
    "teste_criativo": {
        "papel": "especialista em testes de criativo",
        "tarefa": (
            "1) 4 variações mudando SÓ uma coisa (título / abertura / CTA / ângulo).\n"
            "2) O que está sendo testado em cada.\n"
            "3) Ordem de teste."
        ),
        "restricoes": "Uma variável por variação.",
        "formato": "4 variações rotuladas. Ordem de teste recomendada.",
    },
    "sortimento": {
        "papel": "analista de sortimento de e-commerce",
        "tarefa": (
            "1) Cruze demanda ML × meu catálogo: alta demanda que eu não vendo vs. o que vendo com demanda fraca.\n"
            "2) Concorrência e prioridade.\n"
            "3) Até 5 oportunidades a adicionar."
        ),
        "restricoes": "Só dados do JSON. Produto ausente da demanda = não invente. Ignore menção a JoomPulse.",
        "formato": "Oportunidades: Produto | Demanda | Concorrência | Prioridade. Revisar: Produto | O que fazer. Top 5.",
    },
    "analise_financeira": {
        "papel": "analista financeiro de e-commerce",
        "tarefa": (
            "1) Margem estimada R$ e % (mostre a conta).\n"
            "2) Ordene do mais lucrativo ao menos.\n"
            "3) Prejuízo disfarçado."
        ),
        "restricoes": "Dado faltando = incompleto, não chute.",
        "formato": "Produto | Margem R$ | Margem % | Status (saudável/atenção/prejuízo). 3 para revisar preço.",
    },
    "expansao_portfolio": {
        "papel": "consultor de expansão de portfólio",
        "tarefa": (
            "1) Até 3 próximas categorias (demanda real no JSON + proximidade do que já vendo).\n"
            "2) SKUs de entrada e margem se houver dado.\n"
            "3) Qual começar primeiro."
        ),
        "restricoes": "Expansão lógica, não 'primeiro produto da vida'. Sem inventar demanda.",
        "formato": "3 categorias: Categoria | SKUs | Demanda | Margem. Por onde começar.",
    },
    "midia_paga": {
        "papel": "analista de mídia paga para e-commerce",
        "tarefa": (
            "1) Até 5 produtos para concentrar verba agora.\n"
            "2) Quais NÃO anunciar (margem baixa, concorrência alta, demanda fraca).\n"
            "3) Divisão % da verba."
        ),
        "restricoes": "Equilibre margem, demanda e concorrência. Não indique só a maior margem sem demanda.",
        "formato": "Top 5: Produto | Por quê | % verba. Não anunciar: Produto | Motivo.",
    },
    "lacunas_catalogo": {
        "papel": "analista competitivo de e-commerce",
        "tarefa": (
            "1) Sobreposição e lacunas (ele tem, eu não).\n"
            "2) Onde eu tenho vantagem (preço, variação, exclusividade).\n"
            "3) 5 movimentos concretos no próximo mês."
        ),
        "restricoes": "Só o que o JSON mostra. Sem plano genérico.",
        "formato": "Produto | Eu tenho? | Ele tem? | Observação. 5 ações priorizadas.",
    },
    "estoque_zumbis": {
        "papel": "analista de estoque e capital de giro",
        "tarefa": (
            "1) Produtos zumbis (parados, capital preso).\n"
            "2) Liquidar / melhorar anúncio / descontinuar.\n"
            "3) Capital preso se o JSON tiver custo/estoque."
        ),
        "restricoes": "Diferencie morto de sazonal que volta.",
        "formato": "Produto | Vendas | Tempo parado | Capital preso | Recomendação. Qual resolver primeiro.",
    },
    "pricing_dinamico": {
        "papel": "especialista em pricing dinâmico",
        "tarefa": (
            "1) Preço ótimo por SKU (margem × competitividade).\n"
            "2) 1 linha de justificativa.\n"
            "3) Onde estou deixando dinheiro na mesa."
        ),
        "restricoes": "Não recomende guerra de preço sem necessidade. Respeite piso/custo do JSON.",
        "formato": "Produto | Preço atual | Sugerido | Por quê. Onde subir sem perder venda.",
    },
    "reposicao": {
        "papel": "analista de supply e reposição",
        "tarefa": (
            "1) Comprar urgente / pode esperar / não repor.\n"
            "2) Urgentes: quando o estoque acaba no ritmo do JSON.\n"
            "3) Risco de ruptura nos campeões dado o prazo de reposição."
        ),
        "restricoes": "Use o prazo de reposição do JSON para definir urgente.",
        "formato": "3 listas (urgente com data | esperar | não repor). Alerta de ruptura nos campeões.",
    },
    "plano_ataque": {
        "papel": "estrategista competitivo",
        "tarefa": (
            "1) Plano em 5 passos: onde entrar por preço, onde por diferenciação, o que evitar.\n"
            "2) Produtos dele mais vulneráveis.\n"
            "3) Ordem dos movimentos."
        ),
        "restricoes": "Não atacar onde ele é forte e eu sou fraco. Só JSON. Sem JoomPulse.",
        "formato": "5 passos numerados. Primeiro movimento desta semana.",
    },
    "diagnostico_operacao": {
        "papel": "consultor de operação de e-commerce",
        "tarefa": (
            "1) Diagnóstico em 5 pontos: saudável vs. risco.\n"
            "2) Maior gargalo invisível.\n"
            "3) Ação nº1 desta semana."
        ),
        "restricoes": "Direto. Número grave = diga sem rodeio.",
        "formato": "5 pontos. Gargalo: 1 bloco. Ação da semana: 1 recomendação.",
    },
    "bundles": {
        "papel": "especialista em bundles e aumento de ticket",
        "tarefa": (
            "1) Produtos comprados em contextos parecidos.\n"
            "2) Até 5 kits com preço sugerido se houver preço no JSON.\n"
            "3) Aumento de ticket estimado só se der para calcular."
        ),
        "restricoes": "Lógica de uso real, não combo aleatório.",
        "formato": "Kit | Itens | Preço sugerido | Ticket. Kit para lançar primeiro.",
    },
    "auditor_custos_ml": {
        "papel": "auditor de custos do Mercado Livre",
        "tarefa": (
            "1) Onde taxa e frete comem margem.\n"
            "2) Até 5 ajustes (preço, peso, embalagem, tipo de anúncio, kit).\n"
            "3) Ganho estimado se o JSON permitir conta."
        ),
        "restricoes": "Regras reais de faixa de preço/frete só se estiverem no JSON; senão n/d.",
        "formato": "Pontos de perda. 5 ajustes: Ajuste | Ganho | Esforço. O de maior impacto.",
    },
    "predicao_vendas": {
        "papel": "analista preditivo de vendas",
        "tarefa": (
            "1) Produtos em crescimento (mais estoque/verba).\n"
            "2) Produtos em queda.\n"
            "3) Padrão visto nos dados."
        ),
        "restricoes": "Diferencie crescimento real de pico sazonal pontual. Sem série = não preveja.",
        "formato": "Em alta | Em queda (Produto | Padrão | Recomendação). Onde colocar estoque agora.",
    },
    "plano_90_dias": {
        "papel": "consultor de crescimento de e-commerce",
        "tarefa": (
            "1) Plano 90 dias em 3 fases (mês 1/2/3).\n"
            "2) Cada fase: foco, 3 ações, métrica.\n"
            "3) Alinhar ao objetivo do JSON (margem/faturamento/expansão)."
        ),
        "restricoes": "Executável por vendedor pequeno/médio. Sem inventar demanda. Ignore JoomPulse.",
        "formato": "Fase | Foco | 3 ações | Métrica. A ação que destrava o resto.",
    },
}


def id_playbook(proposito: str | None) -> str | None:
    p = (proposito or "").strip().lower()
    if not p:
        return None
    if "ruptura" in p or "guerra" in p:
        return None
    for needle, pid in _MAPA_PROPOSITO:
        if needle in p:
            return pid
    return "panorama_categoria"


def campos_do_json(
    *,
    contexto: dict[str, Any] | None = None,
    consolidado: dict[str, Any] | None = None,
    produto: dict[str, Any] | None = None,
    estado_ml: dict[str, Any] | None = None,
    proposito: str = "",
) -> dict[str, str]:
    ctx = contexto if isinstance(contexto, dict) else {}
    c = consolidado if isinstance(consolidado, dict) else {}
    p = produto if isinstance(produto, dict) else {}
    e = estado_ml if isinstance(estado_ml, dict) else {}

    def _txt(*vals: Any, limite: int = 240) -> str:
        for v in vals:
            if v is None:
                continue
            if isinstance(v, (dict, list)):
                continue
            s = str(v).strip()
            if s:
                return s[:limite]
        return _N_INF

    ramos = ctx.get("empresa_cnpj") if isinstance(ctx.get("empresa_cnpj"), dict) else {}
    ramos_l = ramos.get("ramos") if isinstance(ramos.get("ramos"), list) else []
    nicho = _txt(
        ctx.get("nicho"),
        ctx.get("categoria"),
        c.get("categoria"),
        c.get("nicho"),
        p.get("categoria"),
        ", ".join(str(x) for x in ramos_l[:4]) if ramos_l else None,
        proposito.replace("_", " ") if proposito else None,
    )
    vendas = num(c.get("vendas_totais"), -1)
    qtd_anuncios = num(c.get("total_anuncios_ativos"), -1)
    if vendas > 0 or qtd_anuncios > 0:
        momento = "já vendendo nesse nicho"
    elif e.get("nivel") in ("ok", "atencao", "critico"):
        momento = "conta ML ativa; volume do nicho conforme JSON"
    else:
        momento = _txt(ctx.get("momento"))
    resumo_an = ctx.get("anuncios_ml_resumo") if isinstance(ctx.get("anuncios_ml_resumo"), dict) else {}
    if not resumo_an and isinstance(e.get("anuncios"), dict):
        resumo_an = e["anuncios"]
    n_an = resumo_an.get("total")
    anuncios_resumo = _N_INF
    if n_an is not None:
        anuncios_resumo = (
            f"{int(num(n_an))} itens; publicados={resumo_an.get('publicados')} "
            f"sem_MLB={resumo_an.get('pendente_mlb')} fonte={resumo_an.get('fonte') or '?'}"
        )
    return {
        "nicho": nicho,
        "categoria": nicho,
        "momento": momento,
        "capital_teste": _txt(ctx.get("capital_teste"), ctx.get("investimento")),
        "produto": _txt(p.get("titulo"), p.get("sku"), p.get("nome"), ctx.get("produto")),
        "preco": _txt(p.get("preco"), c.get("preco_medio")),
        "objetivo": _txt(ctx.get("objetivo"), c.get("objetivo"), "conforme estado_ml e JSON"),
        "prazo_reposicao": _txt(ctx.get("prazo_reposicao"), c.get("prazo_reposicao")),
        "marca": _txt(p.get("marca"), ctx.get("marca")),
        "publico": _txt(ctx.get("publico"), c.get("publico")),
        "anuncios_resumo": anuncios_resumo,
    }


def montar_instrucoes(
    playbook_id: str,
    *,
    campos: dict[str, str] | None = None,
) -> str:
    spec = PLAYBOOKS.get(playbook_id) or PLAYBOOKS["panorama_categoria"]
    cam = campos or {}
    ctx_linhas = (
        f"- Nicho/categoria: {cam.get('nicho') or _N_INF}\n"
        f"- Momento: {cam.get('momento') or _N_INF}\n"
        f"- Produto em foco: {cam.get('produto') or _N_INF}\n"
        f"- Anúncios no JSON (anuncios_ml): {cam.get('anuncios_resumo') or _N_INF}\n"
        f"- Faixa/preço: {cam.get('preco') or _N_INF}\n"
        f"- Objetivo agora: {cam.get('objetivo') or _N_INF}\n"
        f"- Capital para testar: {cam.get('capital_teste') or _N_INF}\n"
        f"- Prazo de reposição: {cam.get('prazo_reposicao') or _N_INF}\n"
        "- O restante (concorrente, avaliações, vendas, catálogo, anúncios) está no JSON "
        "(use anuncios_ml / estado_ml.anuncios). "
        "Não use fonte externa (JoomPulse etc.)."
    )
    return (
        f"Você é um {spec['papel']}.\n\n"
        f"CONTEXTO:\n{ctx_linhas}\n\n"
        f"SUA TAREFA:\n{spec['tarefa']}\n\n"
        f"RESTRIÇÕES:\n{spec['restricoes']} "
        "Nunca invente números, demanda, vendas ou reputação ausentes. "
        "Incerteza = sinal fraco / n/d.\n\n"
        f"FORMATO DE SAÍDA:\n{spec['formato']}"
    )


def anexar_playbook(instrucoes_base: str, *, proposito: str) -> tuple[str, str | None]:
    if not cfg_bool("CLAUDE_ML_PLAYBOOKS_ATIVO", True):
        return instrucoes_base, None
    pid = id_playbook(proposito)
    if not pid:
        return instrucoes_base, None
    extra = montar_instrucoes(pid)
    base = (instrucoes_base or "").strip()
    if extra[:40] in base:
        return base, pid
    if not base:
        return extra, pid
    return f"{base}\n\n--- Playbook {pid} ---\n{extra}", pid

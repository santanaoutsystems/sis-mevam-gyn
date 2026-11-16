"""
Gerador de PDF Oficial - SIS MEVAM-GYN
Gera o documento oficial da Ficha de Membro com Aceite da Confissão de Fé,
incorporando a assinatura/rúbrica digital e selo de autenticidade LGPD.
"""

import io
import base64
import os
from datetime import datetime

from .datas import agora as _agora_gyn
from PIL import Image

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY

LOGO_PATH = os.path.join(os.path.dirname(__file__), "static", "img", "logo_round.jpg")

def gerar_pdf_membro(dados_membro: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm
    )

    styles = getSampleStyleSheet()

    # Estilos customizados
    titulo_style = ParagraphStyle(
        'TituloDoc',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#0F274A')
    )

    subtitulo_style = ParagraphStyle(
        'SubtituloDoc',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#2563EB')
    )

    secao_style = ParagraphStyle(
        'SecaoDoc',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#0F274A'),
        spaceBefore=6,
        spaceAfter=4
    )

    corpo_style = ParagraphStyle(
        'CorpoDoc',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#1E293B')
    )

    justificado_style = ParagraphStyle(
        'JustificadoDoc',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        alignment=TA_JUSTIFY,
        textColor=colors.HexColor('#1E293B')
    )

    destaque_style = ParagraphStyle(
        'DestaqueDoc',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#0F274A')
    )

    rodape_style = ParagraphStyle(
        'RodapeDoc',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#64748B')
    )

    story = []

    # --- PÁGINA 1: FICHA DE MEMBROS ---
    header_data = []
    if os.path.exists(LOGO_PATH):
        try:
            img = RLImage(LOGO_PATH, width=1.8 * cm, height=1.8 * cm)
            header_text = Paragraph(
                "<b>MEVAM GYN MINISTÉRIO</b><br/>"
                "<font size=12 color='#0F274A'><b>FICHA DE CADASTRO DE MEMBRO</b></font><br/>"
                "<font size=8 color='#64748B'>Alameda Juazeiro do Norte, 475 – Chácara 79 / Pq. Amazônia - Goiânia - GO</font>",
                titulo_style
            )
            header_table = Table([[img, header_text]], colWidths=[2.5 * cm, 14.5 * cm])
            header_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('ALIGN', (1,0), (1,0), 'CENTER'),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(header_table)
        except Exception:
            story.append(Paragraph("<b>MEVAM GYN - FICHA DE MEMBRO</b>", titulo_style))
    else:
        story.append(Paragraph("<b>MEVAM GYN - FICHA DE MEMBRO</b>", titulo_style))

    story.append(Spacer(1, 0.4 * cm))

    # Data de Registro, Protocolo e Status
    data_reg = dados_membro.get('data_registro') or _agora_gyn().strftime('%d/%m/%Y')
    status_cad = dados_membro.get('status', 'Aguardando Análise')
    proto_info = f"<b>Data do Registro:</b> {data_reg} &nbsp;&nbsp;|&nbsp;&nbsp; <b>ID / Protocolo:</b> #{dados_membro.get('id', 'NOVO')} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Status:</b> <font color='#2563EB'><b>{status_cad.upper()}</b></font>"
    story.append(Paragraph(proto_info, corpo_style))
    story.append(Spacer(1, 0.3 * cm))

    # Foto 3x4 de Identificação Facial (sem óculos)
    foto_3x4_b64 = dados_membro.get('foto_3x4', '')
    foto_element = None
    if foto_3x4_b64 and 'base64,' in foto_3x4_b64:
        try:
            _, b64_str = foto_3x4_b64.split(',', 1)
            foto_bytes = base64.b64decode(b64_str)
            foto_io = io.BytesIO(foto_bytes)
            foto_element = RLImage(foto_io, width=2.7 * cm, height=3.6 * cm)
        except Exception:
            foto_element = None

    if not foto_element:
        ph_text = Paragraph("<font size=7 color='#64748B'><b>FOTO 3x4</b><br/>(SEM ÓCULOS)</font>", ParagraphStyle('PH', parent=styles['Normal'], alignment=TA_CENTER))
        t_ph = Table([[ph_text]], colWidths=[2.7 * cm], rowHeights=[3.6 * cm])
        t_ph.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#94A3B8')),
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F1F5F9'))
        ]))
        foto_element = t_ph

    t_foto_box = Table([[foto_element]], colWidths=[2.9 * cm])
    t_foto_box.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('LEFTPADDING', (0,0), (-1,-1), 2),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))

    # Tabela de Dados Pessoais
    tabela_pessoal_dados = [
        [Paragraph(f"<b>Nome Completo:</b> {dados_membro.get('nome_completo', '')}", corpo_style), ""],
        [Paragraph(f"<b>Endereço:</b> {dados_membro.get('endereco', '')}", corpo_style), ""],
        [
            Paragraph(f"<b>Bairro:</b> {dados_membro.get('bairro', '')}", corpo_style),
            Paragraph(f"<b>Cidade:</b> {dados_membro.get('cidade', 'Goiânia')} &nbsp; <b>CEP:</b> {dados_membro.get('cep', '')}", corpo_style)
        ],
        [
            Paragraph(f"<b>Data de Nascimento:</b> {dados_membro.get('data_nascimento', '')}", corpo_style),
            Paragraph(f"<b>Naturalidade:</b> {dados_membro.get('naturalidade', '')}", corpo_style)
        ],
        [
            Paragraph(f"<b>Sexo:</b> {dados_membro.get('sexo', '')}", corpo_style),
            Paragraph(f"<b>Estado Civil:</b> {dados_membro.get('estado_civil', '')}", corpo_style)
        ],
        [Paragraph(f"<b>Cônjuge:</b> {dados_membro.get('conjuge', 'Não informado')}", corpo_style), ""]
    ]

    t_pessoal = Table(tabela_pessoal_dados, colWidths=[7.0 * cm, 7.1 * cm])
    t_pessoal.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('SPAN', (0, 1), (1, 1)),
        ('SPAN', (0, 5), (1, 5)),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))

    t_master_pessoal = Table([[t_pessoal, t_foto_box]], colWidths=[14.1 * cm, 2.9 * cm])
    t_master_pessoal.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))

    story.append(Paragraph("<b>1. DADOS PESSOAIS E RESIDENCIAIS</b>", secao_style))
    story.append(t_master_pessoal)
    story.append(Spacer(1, 0.3 * cm))

    # Filhos
    story.append(Paragraph("<b>Filhos:</b>", destaque_style))
    filhos = dados_membro.get('filhos', [])
    if isinstance(filhos, str):
        import json
        try: filhos = json.loads(filhos)
        except: filhos = []

    tabela_filhos_dados = [["Nome", "Nascimento", "Idade"]]
    if filhos:
        for f in filhos:
            tabela_filhos_dados.append([
                f.get('nome', '-'),
                f.get('nascimento', '-'),
                str(f.get('idade', '-'))
            ])
    else:
        tabela_filhos_dados.append(["Nenhum filho registrado", "-", "-"])

    t_filhos = Table(tabela_filhos_dados, colWidths=[9 * cm, 4.5 * cm, 3.5 * cm])
    t_filhos.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E2E8F0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#0F274A')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t_filhos)
    story.append(Spacer(1, 0.3 * cm))

    # Contato & Formação
    story.append(Paragraph("<b>2. CONTATO E FORMAÇÃO PROFISSIONAL</b>", secao_style))
    tabela_contato_dados = [
        [
            Paragraph(f"<b>E-mail:</b> {dados_membro.get('email', '')}", corpo_style),
            Paragraph(f"<b>WhatsApp:</b> {dados_membro.get('whatsapp', '')}", corpo_style)
        ],
        [
            Paragraph(f"<b>Telefone:</b> {dados_membro.get('telefone', '')}", corpo_style),
            Paragraph(f"<b>Escolaridade:</b> {dados_membro.get('escolaridade', '')}", corpo_style)
        ],
        [
            Paragraph(f"<b>Formação Acadêmica:</b> {dados_membro.get('formacao_academica', '')}", corpo_style),
            Paragraph(f"<b>Profissão:</b> {dados_membro.get('profissao', '')}", corpo_style)
        ],
        [Paragraph(f"<b>Empresa que trabalha:</b> {dados_membro.get('empresa', '')}", corpo_style), ""]
    ]
    t_contato = Table(tabela_contato_dados, colWidths=[8.5 * cm, 8.5 * cm])
    t_contato.setStyle(TableStyle([
        ('SPAN', (0, 3), (1, 3)),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_contato)
    story.append(Spacer(1, 0.3 * cm))

    # Vida Eclesiástica
    story.append(Paragraph("<b>3. VIDA CRISTÃ E MINISTERIAL</b>", secao_style))
    tabela_eclesia_dados = [
        [
            Paragraph(f"<b>Batizado:</b> {dados_membro.get('batizado', '')}", corpo_style),
            Paragraph(f"<b>Data do batismo:</b> {dados_membro.get('data_batismo', 'Não informado')}", corpo_style)
        ],
        [
            Paragraph(f"<b>Congregava antes?</b> {dados_membro.get('congregava_antes', '')}", corpo_style),
            Paragraph(f"<b>Onde?</b> {dados_membro.get('onde_congregava', 'Não informado')}", corpo_style)
        ],
        [Paragraph(f"<b>Área ministerial que já praticou antes:</b> {dados_membro.get('area_ministerial', 'Nenhuma')}", corpo_style), ""],
        [Paragraph(f"<b>Interesse de batismo na família este ano:</b> {dados_membro.get('interesse_batismo_familia', 'Não informado')}", corpo_style), ""]
    ]
    t_eclesia = Table(tabela_eclesia_dados, colWidths=[8.5 * cm, 8.5 * cm])
    t_eclesia.setStyle(TableStyle([
        ('SPAN', (0, 2), (1, 2)),
        ('SPAN', (0, 3), (1, 3)),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_eclesia)

    # QUEBRA PARA PÁGINA DO CREDO E CONFISSÃO DE FÉ COM ASSINATURA
    story.append(PageBreak())

    # --- PÁGINA 2: CREDO MEVAM GYN / CONFISSÃO DE FÉ ---
    story.append(Paragraph("<b>CREDO MEVAM GYN / CONFISSÃO DE FÉ</b>", titulo_style))
    story.append(Paragraph("<i>MEVAM GYN MINISTÉRIO - Declaração Doutrinária e Termo de Adesão</i>", subtitulo_style))
    story.append(Spacer(1, 0.3 * cm))

    # O Credo
    credo_texto = (
        "<b>Creio em Deus Pai Todo-Poderoso</b>, Criador dos céus e da terra;<br/>"
        "E em Jesus Cristo, seu único Filho, nosso Senhor; O qual foi concebido por obra do Espírito Santo;<br/>"
        "Nasceu da virgem, Maria; Padeceu sob o poder de Pôncio Pilatos; Foi crucificado, morto e sepultado;<br/>"
        "E ao terceiro dia, ressurgiu dos mortos; Subiu ao céu e está assentado à destra de Deus Pai, Todo-Poderoso, "
        "de onde há de vir para julgar os vivos e os mortos;<br/>"
        "Creio no Espírito Santo, Na Santa Igreja de Cristo, Na comunhão dos santos, Na remissão dos pecados, "
        "Na ressurreição do corpo E na vida eterna. <b>Amém!</b>"
    )
    story.append(Paragraph(credo_texto, justificado_style))
    story.append(Spacer(1, 0.25 * cm))

    # Os 10 Artigos Sintetizados com Referências
    artigos = [
        ("1 - A Natureza de Deus e de Seu Cristo",
         "Cremos no único Deus eterno, Criador e Senhor do Mundo, Deus Trino: Pai, Filho e Espírito Santo, que governa todas as coisas segundo a sua vontade. Cremos na divindade de Cristo, seu nascimento virginal, sua morte propiciatória e ressurreição corpórea. Jesus é o único Salvador e mediador entre Deus e os homens. (Is 40:28; Mt 28:19; Jo 17:6; 1Tm 2:5-6)"),
        ("2 - O Ministério do Espírito Santo",
         "Cremos que o Espírito Santo é uma pessoa da Trindade derramado sobre a Igreja em Pentecostes. O Espírito habita em nós para adoração, santificação pessoal, edificação e ministério com todos os dons bíblicos. (1Co 12:4-31; Jo 16:8-11; At 1:8)"),
        ("3 - A Autoridade e o Poder da Bíblia",
         "Afirmamos a inspiração divina, a veracidade e autoridade das Escrituras tanto do Antigo como do Novo Testamento, em sua totalidade, como única Palavra de Deus escrita e regra infalível de fé e prática. (2Tm 3:16; 2Pe 1:21; Mt 5:17-18)"),
        ("4 - A Natureza de Evangelismo e Missões",
         "Evangelizar é difundir a mensagem de salvação em Cristo, chamando ao discipulado: negar a si mesmo, tomar a cruz e identificar-se com a comunidade local. (1Co 15:3-4; Lc 14:25-33; Mt 28:19)"),
        ("5 - A Igreja: Instrumento do Reino e Socialmente Responsável",
         "Acreditamos na Igreja única, santa e universal. A Igreja deve ser ativa na proteção da família, promoção da justiça e libertação dos homens de todo tipo de opressão: O evangelho Todo, Para o Homem Todo, Para Todos os Homens. (Tg 2:14-26; At 17:26)"),
        ("6 - O Retorno de Cristo",
         "Cremos que Jesus Cristo voltará pessoal e visivelmente, em poder e glória, para consumar a salvação e o juízo e reinar para sempre com seu povo. (Hb 9:28; At 1:8-11; Ap 21:1-5)"),
        ("7 - Guerra Espiritual",
         "Cremos no permanente conflito espiritual com potestades do mal, combatendo com as armas espirituais da Palavra e oração com discernimento. (Ef 6:12; 2Co 10:3-5)"),
        ("8 - O Valor da Vida Humana",
         "Todo ser humano é criado à imagem e semelhança de Deus, com dignidade desde a concepção até a morte natural. Posicionamo-nos contra o aborto e o denominamos como homicídio. (Sl 139:13-14; Gn 2:24)"),
        ("9 - A Sexualidade e a Imutabilidade do Casamento",
         "Deus criou os seres humanos intencionalmente nos gêneros masculino e feminino somente. O casamento é uma aliança sagrada entre um homem e uma mulher até que a morte os separe. (Mt 19:4-6; Ef 5:22-26; Gn 2:18)"),
        ("10 - Exortação, Disciplina e Exclusão",
         "Reconhecemos a dinâmica bíblica de exortação, disciplina e restauração em amor e misericórdia conforme Mateus 18:15-17, sob autoridade do presbitério e do Pastor Sênior. (Mt 18:15-17; 1Co 5:1-7; Gl 6:1)")
    ]

    for tit, cont in artigos:
        story.append(Paragraph(f"<b>{tit}</b>: {cont}", justificado_style))
        story.append(Spacer(1, 0.12 * cm))

    story.append(Spacer(1, 0.25 * cm))

    # --- SEÇÃO DE ACEITE E ASSINATURA TIPO RÚBRICA ---
    story.append(Paragraph("<b>DECLARAÇÃO DE ACEITE E CONCORDÂNCIA FORMAL</b>", secao_style))
    termo_aceite = (
        "Declaro para os devidos fins que li integralmente, compreendi e concordo de livre e espontânea vontade "
        "com o Credo e a Confissão de Fé do Ministério MEVAM GYN, submetendo-me aos princípios doutrinários, "
        "estatutários e pastorais desta comunidade de fé."
    )
    story.append(Paragraph(termo_aceite, justificado_style))
    story.append(Spacer(1, 0.3 * cm))

    nome_assinante = dados_membro.get('nome_assinante') or dados_membro.get('nome_completo', '')
    data_assinatura = dados_membro.get('data_assinatura') or _agora_gyn().strftime('%d/%m/%Y %H:%M:%S')
    hash_auth = dados_membro.get('hash_autenticidade', 'AUTHENTICATED-MEVAM-GYN')

    # Tratar imagem da rúbrica / assinatura base64
    rubrica_element = None
    rubrica_b64 = dados_membro.get('assinatura_rubrica', '')
    if rubrica_b64 and 'data:image' in rubrica_b64:
        try:
            cabecalho, base64_str = rubrica_b64.split(',', 1)
            img_bytes = base64.b64decode(base64_str)
            img_io = io.BytesIO(img_bytes)
            rubrica_element = RLImage(img_io, width=4.5 * cm, height=1.6 * cm)
        except Exception:
            rubrica_element = Paragraph("<i>[Rúbrica Digital Gravada]</i>", corpo_style)
    else:
        rubrica_element = Paragraph(
            "<font color='#D97706'><b>PENDENTE DE ANÁLISE / ACEITE PASTORAL</b></font><br/>"
            "<font size=7 color='#64748B'>Aguardando análise da direção e envio do link de confirmação para o membro.</font>",
            corpo_style
        )

    bloco_assinatura = [
        [Paragraph(f"<b>NOME COMPLETO:</b><br/><font size=10 color='#0F274A'><b>{nome_assinante.upper()}</b></font>", corpo_style),
         Paragraph("<b>ASSINATURA / RÚBRICA DIGITAL:</b>", corpo_style)],
        [Paragraph(f"<b>Data/Hora do Aceite:</b> {data_assinatura}<br/><b>Hash LGPD:</b> <font size=6>{hash_auth[:32]}...</font>", corpo_style),
         rubrica_element]
    ]

    t_assinatura = Table(bloco_assinatura, colWidths=[9.5 * cm, 7.5 * cm])
    t_assinatura.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F1F5F9')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#0F274A')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_assinatura)

    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        "MEVAM GYN - Alameda Juazeiro do norte, 475 – Chácara 79 / Pq. Amazônia - Goiânia - Goiás<br/>"
        "Documento assinado digitalmente em conformidade com as diretrizes eclesiásticas e Lei 13.709/2018 (LGPD).",
        rodape_style
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

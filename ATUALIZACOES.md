# SIS MEVAM-GYN • Registro Oficial de Atualizações (Changelog)

Registro cronológico e detalhado de todas as versões do sistema **SIS MEVAM-GYN** (Membros, Gestão Ministerial, Fé & SaaS ERP), utilizando o padrão oficial de versionamento `1.xx`.

---

## 📌 Histórico de Versões

| Versão | Data | Módulo / Foco Principal | Status |
| :--- | :---: | :--- | :---: |
| **v1.26** | Outubro/2026 | **Ficha Cadastral Integral, Desacoplamento do Credo & Validação por QR Code/WhatsApp** | **Ativa / Produção** |
| **v1.25** | Setembro/2026 | Otimização de Agenda, Supabase e Notificações de Escala | Arquivada |
| **v1.24** | Agosto/2026 | Controle de Auditoria, Segurança e Exportação de Relatórios | Arquivada |
| **v1.22** | Julho/2026 | Integração com Supabase Cloud e Painel Mensal de Ministérios | Arquivada |
| **v1.16** | Maio/2026 | Gestão de Voluntários e Escalas Ministeriais com Disparo de E-mail | Arquivada |
| **v1.10** | Março/2026 | Rotinas de Backup, Auditoria e Manual de Operação | Arquivada |
| **v1.4** | Janeiro/2026 | Banco de Dados Relacional e Controle Básico de Membros | Arquivada |
| **v1.0** | 2025 | Lançamento Inicial do Sistema de Gestão MEVAM Goiânia | Arquivada |

---

## 🚀 Detalhamento das Atualizações

### [v1.26] - Outubro/2026 (Atualização Vigente)
**Módulo:** *Ficha Cadastral, Credo Desacoplado & Validação Pastoral com QR Code/WhatsApp*

#### 1. Obrigatoriedade Integral dos Dados Cadastrais
- **Validação Rigorosa das Etapas 1, 2 e 3**:
  - **1. Dados Pessoais & Residenciais:** Nome Completo, Endereço, Bairro, Cidade, CEP, Data de Nascimento, Naturalidade, Sexo, Estado Civil e Nome do Cônjuge (quando casado) são 100% obrigatórios, não sendo permitidos campos em branco ou nulos.
  - **Foto 3x4 Obrigatória:** O envio da foto de identificação facial (arquivo ou câmera) passou a ser pré-requisito mandatório para submissão.
  - **Filhos:** Caso haja preenchimento de filhos na listagem, o nome, data de nascimento e idade passam por validação integral.
  - **2. Contato & Atividade Profissional:** E-mail, WhatsApp com DDD, Telefone, Escolaridade, Formação Acadêmica, Profissão e Empresa de Trabalho com obrigatoriedade estrita.
  - **3. Vida Cristã & Histórico Eclesiástico:** Batismo nas águas, data de batismo, histórico de congregação anterior, igreja onde congregava, áreas ministeriais exercidas e interesse de batismo na família.

#### 2. Salvamento Imediato do Cadastro
- Ao finalizar as etapas cadastrais (seções 1, 2 e 3), o membro aciona o botão **"💾 Salvar Ficha & Enviar para Análise"**.
- O sistema grava o membro imediatamente no banco de dados com o status:
  - **`Aguardando Análise`** (Badge Amarela/Laranja).
- Exibição de modal explicativo informando o membro que os dados foram recebidos pela secretaria e que o link do Credo será enviado após parecer pastoral.

#### 3. Desacoplamento Pastoral da Confissão de Fé e Rúbrica
- A leitura da Confissão de Fé e a assinatura da Rúbrica Digital deixaram de ser imediatas no ato do pré-cadastro, passando a depender da homologação prévia da direção da igreja.
- Implementação de módulo administrativo no **ERP da Secretaria**:
  - Visualização de membros com filtro de status.
  - Botão **"✅ Validar"**: Altera o status para `Validado pela Secretaria`.
  - Botão **"📲 WhatsApp / QR"**: Abre modal exclusivo de compartilhamento.

#### 4. Disparo Inteligente via WhatsApp, E-mail & QR Code
- Geração de **QR Code dinâmico** individual por membro.
- Geração de **Token Seguro e Determinístico** (`token_aceite`) para assegurar que apenas o membro específico acesse seu formulário de aceite.
- Integração de botão com a API do WhatsApp (`https://api.whatsapp.com/send`), já com mensagem pastoral personalizada:
  > *"Graça e Paz, [Nome do Membro]! Sua ficha cadastral foi analisada e validada pela direção do MEVAM GYN. Acesse o link abaixo para ler a Confissão de Fé e realizar a sua rúbrica digital..."*
- Opções adicionais de disparo via cliente de E-mail (`mailto:`) e botão de cópia rápida do link exclusivo.

#### 5. Portal Mobile-First de Aceite e Rúbrica Digital (`/credo-aceite/{id}`)
- Nova página responsiva, otimizada para smartphones (Android e iOS).
- Apresentação solene do Credo dos Apóstolos e dos **10 Artigos Doutrinários** sintetizados com referências bíblicas completas.
- Componente de **Rúbrica Digital** via tela sensível ao toque / mouse (Canvas de Alta Precisão) com:
  - Alternância de cor da tinta (Azul Institucional / Preto Notarial).
  - Botões de limpar e desfazer traço.
  - Gravação de Hash Criptográfico LGPD (IP, data/hora e identificador).
- Botão imediato para **download do PDF Oficial da Ficha de Membro** assinado.

#### 6. Geração de PDF Oficial Aprimorada (`pdf_generator.py`)
- Compatibilidade total com pré-cadastros: exibe indicação de *"Pendente de Análise / Aceite Pastoral"* enquanto não houver assinatura.
- Inclusão do status atual do membro no protocolo do documento (`#ID | STATUS`).
- Emissão em alta resolução A4 com selo de autenticidade LGPD.

---

### [v1.25] - Setembro/2026
- Interface Streamlit com estilização zebrada de alta legibilidade.
- Sincronização automática com Supabase Cloud.
- Ocultação de elementos flutuantes e toolbars para experiência em tela cheia.
- Filtro avançado de agenda mensal e ministerial.

### [v1.24] - Agosto/2026
- Ajustes de conformidade e segurança no envio de notificações por e-mail.
- Geração de relatórios operacionais consolidados de presença.
- Otimização do controle de eventos por ministério.

### [v1.22] - Julho/2026
- Lançamento do layout de calendário com colunas dinâmicas.
- Painel unificado de escalas de voluntários.
- Validação automática de conflitos de datas entre equipes.

### [v1.16] - Maio/2026
- Módulo de disparos de lembretes semanais via SMTP.
- Formulário dinâmico de cadastro de voluntários para eventos de grande porte (ex: Family Day).

### [v1.10] - Março/2026
- Padronização dos manuais de uso e documentação técnica.
- Estruturação do fluxo de auditoria de dados e backups locais.

### [v1.4] - Janeiro/2026
- Criação das tabelas relacionais de membros e departamentos.
- Primeiro protótipo de geração de carteirinhas e fichas físicas.

### [v1.0] - 2025
- Concepção do projeto ministerial para automação da secretaria da igreja MEVAM Goiânia.

---

*Documento mantido pela equipe técnica e de tecnologia do Ministério MEVAM GYN.*

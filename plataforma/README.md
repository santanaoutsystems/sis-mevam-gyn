# SIS MEVAM-GYN · Plataforma Unificada

Une o **app de Membros** (ficha, Credo, rúbrica digital, OCR, PDF) e a **Agenda** (eventos, inscrições,
financeiro, relatórios) num único sistema, com **um login** e **três perfis**:

| Perfil | Ao entrar, vê |
|---|---|
| **Membro** | Agenda (sem dados financeiros nem inscritos), a própria ficha e o PDF dela |
| **Secretaria** | Tudo do Membro + fichas de membros (validar, enviar Credo por WhatsApp/QR, setores, criar login de membro, anonimizar), eventos, inscrições, despesas e relatórios |
| **Administrador** | Tudo da Secretaria + usuários e perfis, setores, auditoria, exportação CSV e exclusão definitiva |

Banco único: **Supabase (Postgres)**. As tabelas da Agenda são usadas como estão; o app só acrescenta tabelas
novas (`membros`, `usuarios`, `membro_setores`, `auditoria`) e colunas opcionais.

## Padrões
- Datas e horas em **America/Sao_Paulo (GMT-03:00)**; entrada e exibição em **dd/mm/aaaa** e **HH:MM** com máscara ativa
  (o usuário digita só números; tecla `h` num campo de data preenche com hoje).
- Telefone, CEP (preenche endereço pelo ViaCEP) e valores em R$ com máscara.
- Preenchimento por voz (🎤) nos campos de texto e datas, em navegadores que suportam (Chrome/Edge/Safari).
- Leitura de ficha em papel ou documento (foto ou PDF) por OCR no próprio aparelho.
- Visual do app de Membros: Plus Jakarta Sans + Outfit, azul real `#1e3a8a`, dourado `#d97706`, cartões arredondados.
- PWA: pode ser instalado na tela inicial do celular. Nenhum dado pessoal fica em cache no aparelho.

## Segurança e LGPD
- Senhas com PBKDF2-SHA256 (600 mil iterações); hashes antigos são atualizados no primeiro login.
- Bloqueio após 5 tentativas erradas (15 min) e limite por IP.
- Sessão em cookie HttpOnly/Secure/SameSite, 12 h; desativar ou trocar o perfil vale na hora.
- Proteção CSRF em todos os formulários; cabeçalhos CSP, HSTS, X-Frame-Options.
- Senha provisória com troca obrigatória no primeiro acesso; nenhum admin ou senha padrão no código.
- Toda visualização de ficha, PDF, exportação, alteração e login fica na **auditoria** (quem, quando, IP).
- Consentimento LGPD registrado na ficha e nas inscrições; anonimização a pedido do titular.
- Links do Credo assinados com a `SECRET_KEY` (não dá para adivinhar o link de outra pessoa).

## Rodar localmente
```bash
cd plataforma
pip install -r requirements.txt
python scripts/dados_demo.py          # banco SQLite de demonstração
uvicorn app.main:app --reload         # http://localhost:8000  (admin@demo.local / Demo1234)
python -m pytest -q tests             # 34 testes
```

## Variáveis de ambiente
| Nome | Obrigatória | Para quê |
|---|---|---|
| `DATABASE_URL` | sim | Conexão Postgres do Supabase (Session pooler) |
| `SECRET_KEY` | sim | Assina sessões e links. Gere com `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `AMBIENTE` | sim | `homologacao` ou `producao` (ativa cookie seguro e exige `SECRET_KEY`) |
| `URL_BASE` | sim | Endereço público, ex. `https://sis-mevam.onrender.com` (usado nos links do WhatsApp) |
| `SMTP_USUARIO` / `SMTP_SENHA` | não | Alertas de evento por e-mail (senha de app do Gmail, **nova**) |

Comando de início: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (pasta raiz do serviço: `plataforma`).

## Roteiro de virada (cada passo só com o OK do Ricardo)
1. **Backup** — `scripts/backup_membros_render.py` (fichas do Render) e `scripts/backup_supabase.py` (Agenda).
2. **Segurança imediata** — revogar a senha de app do Gmail exposta; trocar a senha mestra da Agenda e a senha do admin do app de Membros.
3. **Banco** — rodar `migracoes/001_unificacao.sql` no Supabase (aditiva; a Agenda atual segue funcionando).
4. **Dados** — `scripts/migrar_membros.py backup/membros.json` (simula) e depois com `--executar`;
   `scripts/migrar_logins.py --usuarios-membros backup/usuarios.json --admins seu@email --executar`.
5. **Homologação** — subir um serviço novo no Render apontando para esta pasta; Secretaria testa com os dados reais.
6. **Virada** — divulgar o novo endereço; manter Agenda e Membros antigos só para consulta por alguns dias.
7. **Fechamento** — novo backup e `migracoes/002_pos_virada.sql` (fecha as tabelas antigas para a chave pública).

Os scripts de migração são idempotentes (podem rodar de novo sem duplicar) e não apagam nada da origem.

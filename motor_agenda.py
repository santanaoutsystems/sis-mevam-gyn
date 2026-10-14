from supabase import create_client, Client

# 1. Credenciais do seu Supabase Gratuito
# (Poderá encontrar estes dados no painel do Supabase em Project Settings > API)
URL_SUPABASE = "https://sbitcxnqmjvnfwxccxwq.supabase.co"
CHAVE_SUPABASE = "sb_publishable_sZmAEEZihVmm3ts51XogJg_ECUc4rmg"

def criar_evento_interno():
    # 2. Inicializar a ligação ao seu sistema
    print("A ligar à base de dados do MEVAM...")
    supabase: Client = create_client(URL_SUPABASE, CHAVE_SUPABASE)

    # 3. Estrutura do Evento na sua própria Agenda
    novo_evento = {
        "titulo": "Retiro de Jovens - Teste Interno",
        "data_inicio": "2026-11-15T09:00:00",
        "valor_inscricao": 0.00,
        "limite_vagas": 50
    }

    # 4. Inserção direta na tabela 'eventos'
    try:
        resposta = supabase.table("eventos").insert(novo_evento).execute()
        print("\n✅ Evento criado com sucesso na sua própria agenda!")
        print(f"ID do Evento Gerado: {resposta.data[0]['id']}")
        print(f"Título: {resposta.data[0]['titulo']}")
    except Exception as e:
        print(f"\n❌ Erro ao criar o evento: {e}")
        print("Verifique se a tabela 'eventos' já foi criada no painel do Supabase.")

if __name__ == '__main__':
    criar_evento_interno()
from flask import Flask, render_template, request, redirect, jsonify
import mercadopago
import sqlite3

app = Flask(__name__)

# Configuração do Mercado Pago
sdk = mercadopago.SDK("SEU_ACCESS_TOKEN_AQUI")

def init_db():
    conn = sqlite3.connect("igreja.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inscricoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT NOT NULL,
            telefone TEXT NOT NULL,
            status TEXT DEFAULT 'Pendente',
            payment_id TEXT
        )
    ''')
    conn.commit()
    conn.close()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/checkout", methods=["POST"])
def checkout():
    nome = request.form.get("nome")
    email = request.form.get("email")
    telefone = request.form.get("telefone")

    conn = sqlite3.connect("igreja.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO inscricoes (nome, email, telefone) VALUES (?, ?, ?)", (nome, email, telefone))
    inscricao_id = cursor.lastrowid
    conn.commit()
    conn.close()

    preference_data = {
        "items": [
            {
                "title": "Inscrição Evento Igreja",
                "quantity": 1,
                "unit_price": 50.00,
            }
        ],
        "payer": {
            "name": nome,
            "email": email
        },
        "external_reference": str(inscricao_id),
        "notification_url": "https://seu-dominio-na-internet.com/webhook"
    }

    preference_response = sdk.preference().create(preference_data)
    preference = preference_response["response"]
    
    return redirect(preference["init_point"])

@app.route("/admin")
def admin():
    conn = sqlite3.connect("igreja.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, email, telefone, status FROM inscricoes ORDER BY id DESC")
    inscricoes = cursor.fetchall()
    conn.close()
    
    return render_template("admin.html", inscricoes=inscricoes)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)

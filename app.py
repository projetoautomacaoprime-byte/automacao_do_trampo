from flask import Flask, render_template, request, redirect, url_for, session


# Cria a aplicação Flask
app = Flask(__name__)

# Define uma chave secreta para usar sessões (sessões precisam de uma chave para segurança)
app.secret_key = 'senha_secreta'

# Rota para a página inicial (login)
@app.route('/')
def home():
    # Retorna o template HTML chamado 'login.html'
    return render_template('login.html')

# Rota para o processamento do formulário de login, aceita somente POST (envio de formulário)
@app.route('/login', methods=['POST'])
def login():
    # Pega os dados enviados pelo formulário (username e password)
    username = request.form['username']
    password = request.form['password']
    
    # Verifica se o usuário e senha estão corretos
    if username == 'usuario' and password == 'senha':
        # Marca o usuário como logado na sessão
        session['logged_in'] = True
        # Redireciona para a página do dashboard
        return redirect(url_for('dashboard'))
    
    # Caso usuário/senha incorretos, retorna uma mensagem de erro personalizada
    return 'aaaaaaaaaaaaaah'

# Rota para a página do dashboard (painel)
@app.route('/dashboard')
def dashboard():
    # Verifica se o usuário está logado (se a flag 'logged_in' existe na sessão)
    if not session.get('logged_in'):
        # Se não estiver logado, redireciona para a página de login
        return redirect(url_for('home'))
    
    # Se estiver logado, exibe uma mensagem no dashboard
    return 'MGAAAAAAYYY!'

# Executa a aplicação Flask no modo debug (com recarregamento automático e mensagens de erro)
if __name__ == '__main__':
    app.run(debug=True)

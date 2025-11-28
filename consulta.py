from flask import Blueprint, render_template, session, redirect, url_for

bp = Blueprint('consulta', __name__)

@bp.route('/consulta', methods=['GET'])
def consulta():
    if not session.get('logged_in'):
        return redirect(url_for('auth.home'))
    return render_template('consulta.html', username=session.get('username'))

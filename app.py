    if existing:
        execute('DELETE FROM saved_jobs WHERE id=%s', (existing['id'],))
        return jsonify({'saved': False})
    execute('INSERT INTO saved_jobs (job_id,user_id) VALUES (%s,%s)', (job_id, session['user_id']))
    return jsonify({'saved': True})


@app.get('/api/jobs/saved')
@login_required
def saved_jobs():
    rows = query('''SELECT j.id,j.title,j.company,j.area,j.description,j.location,j.work_type,j.pay,j.deadline,j.created_at,j.user_id,u.name AS author
                    FROM saved_jobs s JOIN jobs j ON j.id=s.job_id JOIN users u ON u.id=j.user_id
                    WHERE s.user_id=%s ORDER BY s.id DESC''', (session['user_id'],))
    for row in rows:
        row['created_at'] = row['created_at'].strftime('%d/%m/%Y') if row.get('created_at') else ''
        if row.get('deadline'):
            row['deadline'] = row['deadline'].strftime('%Y-%m-%d')
    return jsonify({'jobs': rows})


@app.post('/api/jobs/<int:job_id>/apply')
@login_required
def apply_job(job_id):
    job = query('SELECT id,user_id,status FROM jobs WHERE id=%s', (job_id,), one=True)
    if not job or job['status'] != 'open':
        return jsonify({'error': 'Essa vaga não está mais disponível.'}), 404
    if job['user_id'] == session['user_id']:
        return jsonify({'error': 'Você não pode se candidatar à sua própria vaga.'}), 400
    data = request.get_json(silent=True) or {}
    message = clean_text(data.get('message'), 1000)
    existing = query('SELECT id FROM applications WHERE job_id=%s AND user_id=%s', (job_id, session['user_id']), one=True)
    if existing:
        return jsonify({'error': 'Você já se candidatou a essa vaga.'}), 409
    aid = execute('INSERT INTO applications (job_id,user_id,message) VALUES (%s,%s,%s)', (job_id, session['user_id'], message))
    return jsonify({'id': aid}), 201


@app.get('/api/applications/mine')
@login_required
def my_applications():
    rows = query('''SELECT a.id,a.status,a.message,a.created_at,j.id AS job_id,j.title,j.company,j.area,u.name AS employer
                    FROM applications a JOIN jobs j ON j.id=a.job_id JOIN users u ON u.id=j.user_id
                    WHERE a.user_id=%s ORDER BY a.id DESC''', (session['user_id'],))
    for row in rows:
        row['created_at'] = row['created_at'].strftime('%d/%m/%Y %H:%M') if row.get('created_at') else ''
    return jsonify({'applications': rows})


@app.get('/api/jobs/<int:job_id>/applications')
@login_required
def job_applications(job_id):
    job = query('SELECT id FROM jobs WHERE id=%s AND user_id=%s', (job_id, session['user_id']), one=True)
    if not job:
        return jsonify({'error': 'Você não tem permissão para ver essas candidaturas.'}), 403
    rows = query('''SELECT a.id,a.status,a.message,a.created_at,u.name,u.email,u.profession,u.bio,u.location,u.portfolio_url,u.avatar
                    FROM applications a JOIN users u ON u.id=a.user_id WHERE a.job_id=%s ORDER BY a.id DESC''', (job_id,))
    for row in rows:
        row['created_at'] = row['created_at'].strftime('%d/%m/%Y %H:%M') if row.get('created_at') else ''
    return jsonify({'applications': rows})


@app.patch('/api/applications/<int:application_id>')
@login_required
def update_application(application_id):
    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if status not in ('received', 'reviewing', 'selected', 'rejected'):
        return jsonify({'error': 'Status inválido.'}), 400
    row = query('''SELECT a.id FROM applications a JOIN jobs j ON j.id=a.job_id
                   WHERE a.id=%s AND j.user_id=%s''', (application_id, session['user_id']), one=True)
    if not row:
        return jsonify({'error': 'Candidatura não encontrada ou sem permissão.'}), 404
    execute('UPDATE applications SET status=%s WHERE id=%s', (status, application_id))
    return jsonify({'ok': True})


@app.get('/api/jobs/<int:job_id>/savers')
@login_required
def job_savers(job_id):
    job = query('SELECT id FROM jobs WHERE id=%s AND user_id=%s', (job_id, session['user_id']), one=True)
    if not job:
        return jsonify({'error': 'Você não tem permissão para ver esses dados.'}), 403
    # Privacidade: apenas a contagem é exposta, não os nomes dos usuários que salvaram.
    row = query('SELECT COUNT(*) AS total FROM saved_jobs WHERE job_id=%s', (job_id,), one=True)
    return jsonify({'total': row['total']})


@app.errorhandler(413)
def too_large(_error):
    return jsonify({'error': 'O arquivo é muito grande. O limite é 8 MB.'}), 413


@app.errorhandler(500)
def server_error(_error):
    app.logger.exception('Erro interno')
    return jsonify({'error': 'Ocorreu um erro no servidor. Confira o terminal para mais detalhes.'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)

"""Manage RAWAA user accounts from the command line (uses the same DATABASE_URL as the web app).

    python scripts/manage_users.py list
    python scripts/manage_users.py set-password regulator@rawaa.local 'New-Strong-Password'
    python scripts/manage_users.py create inspector@example.org 'Name shown in the app' regulator 'Password'
    python scripts/manage_users.py assign-areas contractor@example.org all        # or: 3,5,8

Roles: regulator (الجهة الرقابية) or operator (المقاول). Changing a password signs that user out
everywhere. Note: the login page's demo buttons only work while the demo passwords are unchanged.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__); return 0
    cmd, args = argv[0], argv[1:]
    with app.connect() as db:
        if cmd == 'list':
            for u in db.execute('SELECT id,email,display,role,created_at FROM users ORDER BY id'):
                n = db.execute('SELECT count(*) FROM areas WHERE assigned_operator=?', (u['id'],)).fetchone()[0]
                print(f"{u['id']:>3}  {u['role']:<9}  {u['email']:<34} {u['display']}  (parks assigned: {n})")
            return 0
        if cmd == 'set-password' and len(args) == 2:
            email, pw = args[0].lower().strip(), args[1]
            if len(pw) < 10:
                print('Password must be at least 10 characters'); return 2
            u = db.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
            if not u:
                print('No such user:', email); return 2
            db.execute('UPDATE users SET pw_hash=? WHERE id=?', (app.password_hash(pw), u['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?', (u['id'],))
            print('Password changed for', email); return 0
        if cmd == 'create' and len(args) == 4:
            email, display, role, pw = args[0].lower().strip(), args[1], args[2], args[3]
            if role not in ('regulator', 'operator'):
                print('Role must be regulator or operator'); return 2
            if len(pw) < 10:
                print('Password must be at least 10 characters'); return 2
            if db.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
                print('User already exists:', email); return 2
            db.execute('INSERT INTO users(email,display,role,pw_hash,created_at) VALUES (?,?,?,?,?)',
                       (email, display, role, app.password_hash(pw), app.utcnow()))
            print('Created', role, email); return 0
        if cmd == 'assign-areas' and len(args) == 2:
            email, which = args[0].lower().strip(), args[1]
            u = db.execute("SELECT id FROM users WHERE email=? AND role='operator'", (email,)).fetchone()
            if not u:
                print('No operator with email', email); return 2
            if which == 'all':
                db.execute('UPDATE areas SET assigned_operator=?', (u['id'],))
            else:
                ids = [int(x) for x in which.split(',') if x.strip()]
                for i in ids:
                    db.execute('UPDATE areas SET assigned_operator=? WHERE id=?', (u['id'], i))
            print('Parks assigned to', email, ':', which); return 0
    print(__doc__); return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

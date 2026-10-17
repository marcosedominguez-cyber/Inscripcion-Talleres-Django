import { useEffect, useState } from 'react';
import { api } from './api.js';

export default function App() {
  const [pantalla, setPantalla] = useState('inicio');
  const [rol, setRol] = useState('participante');
  const [usuario, setUsuario] = useState(null);
  const [iniciando, setIniciando] = useState(true);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');
  const [mensaje, setMensaje] = useState('');

  useEffect(() => {
    let activo = true;
    api('sesion').then(({ usuario }) => {
      if (activo && usuario) {
        setUsuario(usuario);
        setPantalla('cuenta');
      }
    }).catch((e) => { if (activo) setError(e.message); })
      .finally(() => { if (activo) setIniciando(false); });
    return () => { activo = false; };
  }, []);

  function navegar(destino, tipo = 'participante') {
    setPantalla(destino);
    setRol(tipo);
    setError('');
    setMensaje('');
  }

  async function enviar(event) {
    event.preventDefault();
    if (enviando || iniciando) return;
    const datos = Object.fromEntries(new FormData(event.currentTarget));
    setError('');
    setMensaje('');
    if (pantalla === 'registro' && datos.contrasena !== datos.confirmar_contrasena) {
      setError('Las contraseñas no coinciden.');
      return;
    }
    setEnviando(true);
    try {
      // Refrescar CSRF antes de cada operación también permite recuperarse de una sesión caducada.
      await api('sesion');
      if (pantalla === 'registro') {
        const result = await api('registro', { ...datos, rol });
        setPantalla('login');
        setMensaje(result.mensaje);
      } else {
        const result = await api('login', datos);
        setUsuario(result.usuario);
        setPantalla('cuenta');
      }
    } catch (e) {
      setError(e instanceof TypeError ? 'No se pudo conectar con el servidor.' : e.message);
    } finally {
      setEnviando(false);
    }
  }

  async function cerrarSesion() {
    setEnviando(true);
    setError('');
    try {
      await api('sesion');
      await api('logout', {});
      setUsuario(null);
      navegar('inicio');
    } catch (e) { setError(e.message); }
    finally { setEnviando(false); }
  }

  return (
    <main>
      <h1>Inscripción talleres</h1>
      {iniciando && <p role="status">Comprobando sesión…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {mensaje && <p className="mensaje" role="status">{mensaje}</p>}

      {!iniciando && pantalla === 'inicio' && <section aria-label="Inicio">
        <button onClick={() => navegar('login')}>Ingresar o registrarse</button>
        <button className="secundario" onClick={() => navegar('registro', 'instructor')}>¿Quieres publicar talleres?</button>
      </section>}

      {!iniciando && (pantalla === 'login' || pantalla === 'registro') && <section>
        <h2>{pantalla === 'login' ? 'Iniciar sesión' : `Registro de ${rol}`}</h2>
        <form key={`${pantalla}-${rol}`} onSubmit={enviar}>
          {pantalla === 'registro' && <label htmlFor="nombre_usuario">Nombre de usuario
            <input id="nombre_usuario" name="nombre_usuario" autoComplete="username" maxLength={150} required disabled={enviando} />
          </label>}
          <label htmlFor="ci">CI
            <input id="ci" name="ci" type="text" inputMode="numeric" pattern="[0-9]{1,20}" maxLength={20}
              autoComplete={pantalla === 'login' ? 'username' : 'off'} aria-describedby="ci-ayuda" required disabled={enviando} />
          </label>
          <small id="ci-ayuda">Solo números, sin puntos ni guiones.</small>
          <label htmlFor="contrasena">Contraseña
            <input id="contrasena" name="contrasena" type="password"
              autoComplete={pantalla === 'login' ? 'current-password' : 'new-password'}
              required disabled={enviando} />
          </label>
          {pantalla === 'registro' && <>
            <small>Usa al menos 8 caracteres. Evita contraseñas comunes, solo numéricas o similares a tu usuario.</small>
            <label htmlFor="confirmar_contrasena">Confirmar contraseña
              <input id="confirmar_contrasena" name="confirmar_contrasena" type="password" autoComplete="new-password" required disabled={enviando} />
            </label>
          </>}
          <button type="submit" disabled={enviando}>{enviando ? 'Procesando…' : pantalla === 'login' ? 'Ingresar' : 'Crear cuenta'}</button>
        </form>
        <nav aria-label="Opciones de cuenta">
          {pantalla === 'login'
            ? <>
              <button className="enlace" disabled={enviando} onClick={() => navegar('registro')}>Crear cuenta de participante</button>
              <button className="enlace" disabled={enviando} onClick={() => navegar('registro', 'instructor')}>¿Quieres publicar talleres?</button>
            </>
            : <button className="enlace" disabled={enviando} onClick={() => navegar('login')}>Ya tengo cuenta. Iniciar sesión</button>}
          <button className="enlace" disabled={enviando} onClick={() => navegar('inicio')}>Volver al inicio</button>
        </nav>
      </section>}

      {!iniciando && pantalla === 'cuenta' && usuario && <section>
        <h2>Sesión iniciada</h2>
        <p>Hola, {usuario.nombre_usuario}.</p>
        <p>Rol: <strong>{usuario.rol_nombre}</strong></p>
        <p>Tu panel de talleres está pendiente de integración con el equipo.</p>
        <button onClick={cerrarSesion} disabled={enviando}>{enviando ? 'Cerrando…' : 'Cerrar sesión'}</button>
      </section>}
    </main>
  );
}

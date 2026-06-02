import { useState } from 'react'
import { supabase } from './supabaseClient'

export default function Auth({ setSession }) {
  const [loading, setLoading] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLogin, setIsLogin] = useState(true)
  const [message, setMessage] = useState(null)

  const handleAuth = async (e) => {
    e.preventDefault()
    setLoading(true)
    setMessage(null)

    try {
      if (isLogin) {
        const { error, data } = await supabase.auth.signInWithPassword({ email, password })
        if (error) throw error
        setSession(data.session)
      } else {
        const { error } = await supabase.auth.signUp({ email, password })
        if (error) throw error
        setMessage('Check your email for the login link or try logging in if auto-confirm is enabled.')
      }
    } catch (error) {
      setMessage(error.error_description || error.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="home-screen" style={{ justifyContent: 'center' }}>
      <div className="home-header">
        <h1>{isLogin ? 'Login' : 'Sign Up'}</h1>
        <p>Please {isLogin ? 'login' : 'sign up'} to continue</p>
      </div>
      <form onSubmit={handleAuth} style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '300px', width: '100%', margin: '0 auto' }}>
        <input
          className="chat-input"
          type="email"
          placeholder="Email address"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          className="chat-input"
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <button className="generate-button" type="submit" disabled={loading}>
          {loading ? 'Loading...' : (isLogin ? 'Login' : 'Sign Up')}
        </button>
      </form>
      {message && <div style={{ marginTop: '16px', textAlign: 'center', color: message.includes('error') || message.includes('Invalid') ? '#ff4d4f' : '#4caf50' }}>{message}</div>}
      <div style={{ marginTop: '24px', textAlign: 'center' }}>
        <button 
          className="secondary-button" 
          onClick={() => setIsLogin(!isLogin)}
        >
          {isLogin ? 'Need an account? Sign Up' : 'Already have an account? Login'}
        </button>
      </div>
    </div>
  )
}

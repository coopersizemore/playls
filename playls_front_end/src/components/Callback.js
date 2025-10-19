// src/pages/SpotifyCallback.js
import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const Callback = () => {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { setUser } = useAuth();

  useEffect(() => {
    const token = params.get('token');
    const userId = params.get('user_id');

    console.log("Callback params:", { token, userId });
    if (token && userId) {
      localStorage.setItem('accessToken', token);
      localStorage.setItem('userId', userId);
      setUser({ id: userId, accessToken: token });
      navigate('/');
    } else {
      navigate('/login');
    }
  }, [params, navigate, setUser]);

  return <p>Logging you in...</p>;
};

export default Callback;

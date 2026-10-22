import { useNavigate } from 'react-router-dom';
import { setToken } from './api.js';

export function useLogout() {
  const navigate = useNavigate();
  return () => {
    setToken(null);
    navigate('/login');
  };
}

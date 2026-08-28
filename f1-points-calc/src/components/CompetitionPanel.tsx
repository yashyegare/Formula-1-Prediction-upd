import { Provider } from 'react-redux';
import { store } from '../store';
import Compete from '../views/Compete';

export default function CompetitionPanel() {
  return (
    <Provider store={store}>
      <Compete />
    </Provider>
  );
}

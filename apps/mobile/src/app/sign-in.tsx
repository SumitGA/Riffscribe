import { AuthView } from '@clerk/expo/native';
import { View } from 'react-native';

// Clerk's native sign-in and sign-up: email + password, Google, and Apple on iOS, as enabled in
// the Clerk dashboard. When it completes, the root layout's guard swaps to the home screen.
export default function SignIn() {
  return (
    <View style={{ flex: 1 }}>
      <AuthView mode="signInOrUp" isDismissible={false} />
    </View>
  );
}

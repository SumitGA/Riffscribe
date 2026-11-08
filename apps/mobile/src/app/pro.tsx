import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { Check } from 'lucide-react-native';
import { useState } from 'react';
import { Alert, Linking, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useApi } from '@/api/provider';
import {
  billingAvailable,
  buy,
  manageSubscription,
  type ProOption,
  proOptions,
  restore,
  STORE_ACCOUNT,
  STORE_NAME,
} from '@/billing';
import { PRO_BENEFITS } from '@/billing/plan';
import { legalUrl } from '@/legal/links';
import { colors, fonts, radius, space } from '@/theme';
import { Button, Card, Text } from '@/ui';

/** Why the paywall opened, for its first line. */
const REASONS: Record<string, string> = {
  limit: 'You’ve used this month’s free transcriptions.',
  length: 'This recording is longer than the free plan’s 5 minutes.',
};

function optionLabel(option: ProOption): string {
  return option.period === 'year' ? 'Yearly' : 'Monthly';
}

function optionPrice(option: ProOption): string {
  return `${option.price} / ${option.period}`;
}

/** The auto-renewal wording both stores require next to the subscribe button. */
export function renewalTerms(option: ProOption): string {
  const start = option.trial ? `${option.trial}, then ${optionPrice(option)}` : optionPrice(option);
  return (
    `${start}. Renews automatically until you cancel. Payment is charged to your ` +
    `${STORE_ACCOUNT} when you confirm. Cancel at least 24 hours before the end of a period ` +
    `to avoid the next charge, in ${STORE_NAME}’s subscription settings.`
  );
}

/**
 * The Pro paywall (ADR-0016): what Pro gives, the store's prices, the auto-renewal terms the
 * stores require, Restore Purchases, and the Terms and Privacy links. The store's own sheet
 * takes the payment; the server then re-checks what the user owns.
 */
export default function Pro() {
  const { reason } = useLocalSearchParams<{ reason?: string }>();
  const api = useApi();
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: api.me });
  const options = useQuery({
    queryKey: ['pro-options'],
    queryFn: proOptions,
    enabled: billingAvailable(),
    staleTime: 5 * 60 * 1000,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const chosen =
    options.data?.find((o) => o.id === selectedId) ??
    options.data?.find((o) => o.period === 'year') ??
    options.data?.[0];

  // The server decides the plan; ask it to re-check now instead of waiting for the store's
  // notification. If that fails, the notification still arrives within a minute or so.
  const refreshPlan = async () => {
    await api.syncBilling().catch(() => {});
    return queryClient.fetchQuery({ queryKey: ['me'], queryFn: api.me, staleTime: 0 });
  };

  const purchase = useMutation({
    mutationFn: async (option: ProOption) => {
      if (!(await buy(option))) {
        return null; // cancelled in the store's sheet
      }
      return refreshPlan();
    },
    onSuccess: (updated) => {
      if (!updated) {
        return;
      }
      if (updated.plan === 'free') {
        Alert.alert(
          'Payment received',
          'Pro will turn on in a minute or so. Pull to refresh the Library if it doesn’t.',
        );
      } else {
        Alert.alert('Welcome to Pro', 'Your new limits apply to your next transcription.');
      }
      router.back();
    },
    onError: (error) => Alert.alert('The purchase didn’t go through', error.message),
  });

  const restoreMutation = useMutation({
    mutationFn: async () => {
      await restore();
      return refreshPlan();
    },
    onSuccess: (updated) => {
      if (updated.plan === 'free') {
        Alert.alert(
          'Nothing to restore',
          `No active Riffscribe Pro subscription was found for this ${STORE_ACCOUNT}.`,
        );
      } else {
        Alert.alert('Pro restored', 'Your subscription is on this account again.');
        router.back();
      }
    },
    onError: (error) => Alert.alert('Couldn’t restore purchases', error.message),
  });

  const busy = purchase.isPending || restoreMutation.isPending;
  const alreadyPro = me.data?.plan === 'pro' && me.data.plan_source === 'store';
  const reasonText = reason ? REASONS[reason] : undefined;

  return (
    <SafeAreaView edges={['bottom']} style={styles.screen}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.hero}>
          <Text variant="title" accessibilityRole="header">
            Riffscribe Pro
          </Text>
          {reasonText && (
            <Text variant="muted" testID="pro-reason">
              {reasonText}
            </Text>
          )}
        </View>

        <Card style={styles.benefits}>
          {PRO_BENEFITS.map((b) => (
            <View key={b.title} style={styles.benefit}>
              <Check color={colors.accent} size={20} />
              <View style={styles.benefitText}>
                <Text variant="label">{b.title}</Text>
                <Text variant="muted">{b.detail}</Text>
              </View>
            </View>
          ))}
          <Text variant="caption">Everything you transcribe stays yours if you stop.</Text>
        </Card>

        {alreadyPro ? (
          <Card style={styles.notice}>
            <Text variant="label">You’re on Pro.</Text>
            <Button
              title="Manage subscription"
              kind="secondary"
              onPress={() => void manageSubscription()}
            />
          </Card>
        ) : !billingAvailable() ? (
          <Text variant="muted" style={styles.centered}>
            Pro isn’t available in this version of the app.
          </Text>
        ) : options.isPending ? (
          <Text variant="muted" style={styles.centered}>
            Loading prices…
          </Text>
        ) : options.isError || !chosen ? (
          <View style={styles.notice}>
            <Text variant="muted" style={styles.centered}>
              Couldn’t load prices from {STORE_NAME}. Check your connection and try again.
            </Text>
            <Button title="Try again" kind="secondary" onPress={() => void options.refetch()} />
          </View>
        ) : (
          <View style={styles.options} accessibilityRole="radiogroup">
            {options.data.map((option) => {
              const selected = option.id === chosen.id;
              return (
                <Pressable
                  key={option.id}
                  accessibilityRole="radio"
                  accessibilityState={{ selected }}
                  accessibilityLabel={`${optionLabel(option)}, ${optionPrice(option)}`}
                  onPress={() => setSelectedId(option.id)}
                  style={[styles.option, selected && styles.optionSelected]}
                >
                  <View style={styles.optionText}>
                    <Text variant="label">{optionLabel(option)}</Text>
                    {option.perMonth && <Text variant="muted">{option.perMonth} a month</Text>}
                    {option.trial && <Text style={styles.trial}>{option.trial}</Text>}
                  </View>
                  <Text style={styles.price}>{optionPrice(option)}</Text>
                </Pressable>
              );
            })}
          </View>
        )}

        {!alreadyPro && chosen && (
          <Text variant="caption" style={styles.fine} testID="renewal-terms">
            {renewalTerms(chosen)}
          </Text>
        )}

        <View style={styles.links}>
          <Text
            variant="caption"
            accessibilityRole="link"
            style={styles.link}
            onPress={() => void Linking.openURL(legalUrl('terms'))}
          >
            Terms of Use
          </Text>
          <Text variant="caption">·</Text>
          <Text
            variant="caption"
            accessibilityRole="link"
            style={styles.link}
            onPress={() => void Linking.openURL(legalUrl('privacy'))}
          >
            Privacy Policy
          </Text>
        </View>
      </ScrollView>

      {!alreadyPro && billingAvailable() && (
        <View style={styles.actions}>
          <Button
            title={chosen?.trial ? 'Start free trial' : 'Subscribe'}
            loading={purchase.isPending}
            disabled={!chosen || busy}
            onPress={() => chosen && purchase.mutate(chosen)}
          />
          <Button
            title="Restore purchases"
            kind="secondary"
            loading={restoreMutation.isPending}
            disabled={busy}
            onPress={() => restoreMutation.mutate()}
          />
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: { padding: space.xl, gap: space.xl },
  hero: { gap: space.sm },
  benefits: { gap: space.lg },
  benefit: { flexDirection: 'row', gap: space.md, alignItems: 'flex-start' },
  benefitText: { flex: 1, gap: 2 },
  options: { gap: space.md },
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: space.lg,
    borderRadius: radius.lg,
    borderWidth: 1.5,
    borderColor: colors.line,
    backgroundColor: colors.surface,
  },
  optionSelected: { borderColor: colors.accent, backgroundColor: colors.raised },
  optionText: { flex: 1, gap: 2 },
  price: { fontFamily: fonts.monoBold, color: colors.text, fontSize: 15 },
  trial: { color: colors.success, fontFamily: fonts.bodySemiBold },
  notice: { gap: space.md },
  centered: { textAlign: 'center' },
  fine: { lineHeight: 18 },
  links: { flexDirection: 'row', justifyContent: 'center', gap: space.sm },
  link: { color: colors.accent, textDecorationLine: 'underline' },
  actions: { paddingHorizontal: space.xl, paddingTop: space.md, gap: space.sm },
});

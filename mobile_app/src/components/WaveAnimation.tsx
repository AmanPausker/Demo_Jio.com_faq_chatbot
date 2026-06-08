import React, { useEffect } from 'react';
import { View, StyleSheet } from 'react-native';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withSequence,
  withTiming,
  withDelay,
  Easing,
  cancelAnimation
} from 'react-native-reanimated';

export type WaveType = 'idle' | 'user' | 'assistant';

interface Props {
  type: WaveType;
}

const BARS = 60;
const RADIUS = 80;

export function WaveAnimation({ type }: Props) {
  // Array of shared values for each bar
  const animations = Array.from({ length: BARS }).map(() => useSharedValue(0.3));

  useEffect(() => {
    if (type === 'idle') {
      animations.forEach((anim) => {
        cancelAnimation(anim);
        anim.value = withTiming(0.3, { duration: 300 });
      });
      return;
    }

    const duration = 250;
    
    animations.forEach((anim, i) => {
      cancelAnimation(anim);
      
      // Randomize the delay to create an organic waveform
      const baseDelay = Math.random() * 400; 
      
      anim.value = withDelay(
        baseDelay,
        withRepeat(
          withSequence(
            withTiming(Math.random() * 1.5 + 0.5, { duration: duration + Math.random() * 200, easing: Easing.inOut(Easing.ease) }),
            withTiming(0.3, { duration: duration + Math.random() * 200, easing: Easing.inOut(Easing.ease) })
          ),
          -1,
          false
        )
      );
    });
  }, [type]);

  const getColor = (i: number) => {
    if (type === 'user') {
      // Cyan to blue gradient
      const hue = 190 + (i / BARS) * 50; 
      return `hsla(${hue}, 90%, 60%, 0.65)`;
    } else if (type === 'assistant') {
      // Orange/Red to Purple gradient (matches the image vibe)
      const hue = 330 + (i / BARS) * 60;
      return `hsla(${hue % 360}, 90%, 60%, 0.65)`;
    }
    return 'rgba(255,255,255,0.4)'; // idle
  };

  return (
    <View style={styles.container}>
      {animations.map((anim, i) => {
        const rotation = i * (360 / BARS);
        const style = useAnimatedStyle(() => {
          return {
            transform: [
              { rotate: `${rotation}deg` },
              { translateY: -RADIUS },
              { scaleY: anim.value }
            ],
          };
        });
        return <Animated.View key={i} style={[styles.bar, style, { backgroundColor: getColor(i) }]} />;
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    height: RADIUS * 2 + 100, // accommodate radius + bars
    marginVertical: 20,
    width: '100%'
  },
  bar: {
    position: 'absolute',
    top: '50%',
    left: '50%',
    marginTop: -20,
    marginLeft: -2,
    width: 4,
    height: 40,
    borderRadius: 2,
  },
});

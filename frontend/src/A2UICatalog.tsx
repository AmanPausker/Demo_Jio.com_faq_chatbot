import React from 'react';

const getWeatherImage = (condition) => {
    const c = condition.toLowerCase();
    if (c.includes('rain') || c.includes('drizzle')) return '🌧️';
    if (c.includes('cloud')) return '☁️';
    if (c.includes('sun') || c.includes('clear')) return '☀️';
    if (c.includes('snow')) return '❄️';
    if (c.includes('thunder') || c.includes('storm')) return '⛈️';
    if (c.includes('haze') || c.includes('fog') || c.includes('mist')) return '🌫️';
    return '🌡️';
};

import { createComponentImplementation, basicCatalog } from '@a2ui/react/v0_9';
import { Catalog } from '@a2ui/web_core/v0_9';
import { z } from 'zod';

const WeatherCardApi = {
    name: 'WeatherCard',
    schema: z.object({
        city: z.string(),
        temperature: z.number(),
        condition: z.string(),
    })
};

const WeatherCardImpl = createComponentImplementation(WeatherCardApi, ({ props }) => (
    <div style={{
        padding: '20px',
        border: '1px solid #e5e7eb',
        borderRadius: '12px',
        boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
        backgroundColor: '#eff6ff',
        color: '#1e3a8a',
        width: 'fit-content',
        minWidth: '320px',
        display: 'flex',
        alignItems: 'center',
        gap: '24px'
    }}>
        <div style={{ fontSize: '4rem', lineHeight: 1 }}>
            {getWeatherImage(props.condition)}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <h2 style={{ fontSize: '1.5rem', fontWeight: 'bold', margin: 0 }}>{props.city}</h2>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
                <span style={{ fontSize: '2.5rem', fontWeight: '600' }}>{props.temperature}°C</span>
                <span style={{ color: '#4b5563', textTransform: 'capitalize', fontSize: '1.125rem' }}>{props.condition}</span>
            </div>
        </div>
    </div>
));

export const myCatalog = new Catalog(
    'https://example.com/my-catalog.json',
    [...basicCatalog.components.values(), WeatherCardImpl],
    basicCatalog.functions
);
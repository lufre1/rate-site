import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

function Impressum({ onBack }) {
  const { t } = useTranslation();

  return (
    <div style={{ maxWidth: '600px', margin: '0 auto', padding: '24px' }}>
      <h1 style={{ fontSize: '1.5rem', fontWeight: '700', color: '#1f2937', marginBottom: '24px' }}>
        {t('impressum.title')}
      </h1>
      <div style={{ lineHeight: '1.8', color: '#374151' }}>
        <p style={{ marginBottom: '12px' }}>
          <strong>{t('impressum.name')}:</strong><br />
          Luca Freckmann<br />
          Goldschmidstraße 1<br />
          37077 Göttingen
        </p>
 <p style={{ marginBottom: '12px' }}>
            <strong>{t('impressum.contact')}:</strong><br />
            {t('impressum.email')}: <a href="mailto:luca.freckmann@stud.uni-goettingen.de" style={{ color: '#ea580c', textDecoration: 'none', fontWeight: 500 }}>luca.freckmann@stud.uni-goettingen.de</a>
          </p>
        <hr style={{ border: 'none', borderTop: '1px solid #f3f4f6', margin: '24px 0' }} />
 <p style={{ fontSize: '0.875rem', color: '#6b7280', marginTop: '16px' }}>
            {t('impressum.disclaimerText')}
          </p>
      </div>
      <button
        onClick={onBack}
        style={{
          marginTop: '24px',
          padding: '8px 16px',
          background: '#ea580c',
          color: '#fff',
          border: 'none',
          borderRadius: '8px',
          cursor: 'pointer',
          fontSize: '0.875rem',
          fontWeight: 600,
          transition: 'all 0.2s ease',
          boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
        }}
      >
        {t('impressum.back')}
      </button>
    </div>
  );
}

export default Impressum;

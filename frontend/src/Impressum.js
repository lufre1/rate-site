import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

function Impressum({ onBack }) {
  const { t } = useTranslation();

  return (
    <div style={{ maxWidth: '600px', margin: '0 auto', padding: '24px' }}>
      <h1 style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#1f2937', marginBottom: '24px' }}>
        {t('impressum.title')}
      </h1>
      <div style={{ lineHeight: '1.6', color: '#374151' }}>
        <p style={{ marginBottom: '12px' }}>
          <strong>{t('impressum.name')}:</strong><br />
          Luca Freckmann<br />
          Goldschmidstraße 1<br />
          37077 Göttingen
        </p>
<p style={{ marginBottom: '12px' }}>
           <strong>{t('impressum.contact')}:</strong><br />
           {t('impressum.email')}: <a href="mailto:luca.freckmann@stud.uni-goettingen.de" style={{ color: '#3b82f6', textDecoration: 'none' }}>luca.freckmann@stud.uni-goettingen.de</a>
         </p>
        <hr style={{ border: 'none', borderTop: '1px solid #e5e7eb', margin: '24px 0' }} />
<p style={{ fontSize: '0.875rem', color: '#6b7280', marginTop: '16px' }}>
           {t('impressum.disclaimerText')}
         </p>
      </div>
      <button
        onClick={onBack}
        style={{
          marginTop: '24px',
          padding: '8px 16px',
          background: '#3b82f6',
          color: '#fff',
          border: 'none',
          borderRadius: '4px',
          cursor: 'pointer',
          fontSize: '0.875rem'
        }}
      >
        {t('impressum.back')}
      </button>
    </div>
  );
}

export default Impressum;

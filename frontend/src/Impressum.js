import React from 'react';
import { useTranslation } from 'react-i18next';

function Impressum({ onBack }) {
  const { t } = useTranslation();

  return (
    <div className="page--narrow">
      <h2 className="view-title">{t('impressum.title')}</h2>
      <div className="prose">
        <p>
          <strong>{t('impressum.name')}:</strong><br />
          Luca Freckmann<br />
          Goldschmidstraße 1<br />
          37077 Göttingen
        </p>
        <p>
          <strong>{t('impressum.contact')}:</strong><br />
          {t('impressum.email')}:{' '}
          <a href="mailto:luca.freckmann@stud.uni-goettingen.de">
            luca.freckmann@stud.uni-goettingen.de
          </a>
        </p>
        <hr className="rule" />
        <p className="muted-text">{t('impressum.disclaimerText')}</p>
      </div>
      <button type="button" className="btn btn--primary mt-6" onClick={onBack}>
        {t('impressum.back')}
      </button>
    </div>
  );
}

export default Impressum;

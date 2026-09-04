import React from 'react';
import { useTranslation } from 'react-i18next';

const EMAIL = 'luca.freckmann@stud.uni-goettingen.de';

// Private, non-commercial project: no postal address is published, and
// impressum.natureText is the clause that says why (no obligation under
// § 5 DDG, which binds only geschaeftsmaessige Telemedien). Do not add an
// address back without changing that paragraph too.
function Impressum({ onBack }) {
  const { t } = useTranslation();

  return (
    <div className="page--narrow">
      <h2 className="view-title">{t('impressum.title')}</h2>
      <div className="prose">
        <p>
          <strong>{t('impressum.name')}:</strong><br />
          Luca Freckmann
        </p>
        <p>
          <strong>{t('impressum.contact')}:</strong><br />
          {t('impressum.email')}: <a href={`mailto:${EMAIL}`}>{EMAIL}</a>
        </p>

        <h3>{t('impressum.nature')}</h3>
        <p>{t('impressum.natureText')}</p>

        <hr className="rule" />

        <h3>{t('impressum.liability')}</h3>
        <p>{t('impressum.disclaimerText')}</p>

        <h3>{t('impressum.links')}</h3>
        <p>{t('impressum.linksText')}</p>

        <h3>{t('impressum.userContent')}</h3>
        <p>{t('impressum.userContentText')}</p>

        <h3>{t('impressum.affiliation')}</h3>
        <p className="muted-text">{t('impressum.affiliationText')}</p>
      </div>
      <button type="button" className="btn btn--primary mt-6" onClick={onBack}>
        {t('ui.backHome')}
      </button>
    </div>
  );
}

export default Impressum;

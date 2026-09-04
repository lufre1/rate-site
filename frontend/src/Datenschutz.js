import React from 'react';
import { useTranslation } from 'react-i18next';

const EMAIL = 'luca.freckmann@stud.uni-goettingen.de';

// Every factual claim on this page is checked against the code. If you change
// what the site stores, change this page in the same commit -- in particular:
//   * server log fields and rotation  -> nginx-proxy.conf (log_format proxymain)
//   * the localStorage keys           -> shared.js
//   * what a rating publishes         -> rating_identity() in main.py
//   * EXIF removal on upload          -> strip_metadata() in backend/images.py
//   * backup retention                -> DAILY_KEEP_DAYS / WEEKLY_KEEP_DAYS in ops/lib.sh
function Datenschutz({ onBack }) {
  const { t } = useTranslation();

  return (
    <div className="page--narrow">
      <h2 className="view-title">{t('datenschutz.title')}</h2>
      <div className="prose">
        <p className="muted-text">{t('datenschutz.updated')}</p>
        <p>{t('datenschutz.intro')}</p>

        <h3>{t('datenschutz.controller')}</h3>
        <p>
          {t('datenschutz.controllerText')}<br />
          Luca Freckmann<br />
          <a href={`mailto:${EMAIL}`}>{EMAIL}</a>
        </p>

        <h3>{t('datenschutz.hosting')}</h3>
        <p>{t('datenschutz.hostingText')}</p>

        <h3>{t('datenschutz.logs')}</h3>
        <p>{t('datenschutz.logsText')}</p>
        <ul>
          <li>{t('datenschutz.logsIp')}</li>
          <li>{t('datenschutz.logsTime')}</li>
          <li>{t('datenschutz.logsRequest')}</li>
          <li>{t('datenschutz.logsStatus')}</li>
          <li>{t('datenschutz.logsReferrer')}</li>
          <li>{t('datenschutz.logsAgent')}</li>
        </ul>
        <p>{t('datenschutz.logsPurpose')}</p>
        <p>{t('datenschutz.logsRetention')}</p>

        <h3>{t('datenschutz.storage')}</h3>
        <p>{t('datenschutz.storageText')}</p>
        <ul>
          <li>{t('datenschutz.storageToken')}</li>
          <li>{t('datenschutz.storageTheme')}</li>
          <li>{t('datenschutz.storageVoter')}</li>
        </ul>
        <p>{t('datenschutz.storageDelete')}</p>

        <h3>{t('datenschutz.account')}</h3>
        <p>{t('datenschutz.accountText')}</p>
        <p>{t('datenschutz.accountNoEmail')}</p>
        <p>{t('datenschutz.accountSession')}</p>

        <h3>{t('datenschutz.content')}</h3>
        <p>{t('datenschutz.contentText')}</p>
        <p>{t('datenschutz.contentAnon')}</p>
        <p>{t('datenschutz.contentPhotos')}</p>
        <p>{t('datenschutz.contentExif')}</p>

        <h3>{t('datenschutz.votes')}</h3>
        <p>{t('datenschutz.votesText')}</p>

        <h3>{t('datenschutz.external')}</h3>
        <p>{t('datenschutz.externalText')}</p>

        <h3>{t('datenschutz.retention')}</h3>
        <p>{t('datenschutz.retentionText')}</p>

        <hr className="rule" />

        <h3>{t('datenschutz.rights')}</h3>
        <p>{t('datenschutz.rightsText')}</p>
        <ul>
          <li>{t('datenschutz.rightsAccess')}</li>
          <li>{t('datenschutz.rightsRectify')}</li>
          <li>{t('datenschutz.rightsErase')}</li>
          <li>{t('datenschutz.rightsRestrict')}</li>
          <li>{t('datenschutz.rightsPortability')}</li>
          <li>{t('datenschutz.rightsObject')}</li>
        </ul>
        <p>{t('datenschutz.rightsSelf')}</p>
        <p>{t('datenschutz.rightsHow')}</p>
        <p className="muted-text">{t('datenschutz.rightsCaveatName')}</p>
        <p className="muted-text">{t('datenschutz.rightsCaveatSides')}</p>

        <h3>{t('datenschutz.complaint')}</h3>
        <p>{t('datenschutz.complaintText')}</p>

        <h3>{t('datenschutz.none')}</h3>
        <p>{t('datenschutz.noneText')}</p>
      </div>
      <button type="button" className="btn btn--primary mt-6" onClick={onBack}>
        {t('ui.backHome')}
      </button>
    </div>
  );
}

export default Datenschutz;

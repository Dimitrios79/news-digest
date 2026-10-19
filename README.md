# Daily Brief — αυτόματο ημερήσιο δελτίο ειδήσεων

Κάθε πρωί (07:47 ώρα Ελλάδας/Βουλγαρίας) ένα GitHub Action:

1. μαζεύει τα άρθρα του τελευταίου 24ώρου από τα RSS του `feeds.yaml`,
2. το Claude γράφει ουδέτερες περιλήψεις σε **Ελληνικά και Αγγλικά** (μόνο γεγονότα, ρητή απόδοση δηλώσεων, συγχώνευση ίδιων ειδήσεων από πολλές πηγές),
3. χτίζεται στατικό site και ανεβαίνει στο GitHub Pages,
4. (προαιρετικά) φεύγει το δελτίο ως newsletter.

Ενότητες: Κυβερνοασφάλεια & AI Security · Τεχνολογία · Ελλάδα · Βουλγαρία.

## Στήσιμο (10 λεπτά)

1. **Repo**: φτιάξε νέο repo στο GitHub (π.χ. `news-digest`) και κάνε push αυτόν τον φάκελο στο `main`.
2. **Pages**: Settings → Pages → *Build and deployment* → Source: **GitHub Actions**.
3. **AI**: δεν χρειάζεται τίποτα — χρησιμοποιείται **δωρεάν το GitHub Models** μέσω του token του workflow.  
   Προαιρετικά, για καλύτερη ποιότητα (επί πληρωμή): secret `ANTHROPIC_API_KEY` από το console.anthropic.com — αν υπάρχει, προτιμάται αυτόματα.
4. **site.yaml**: άλλαξε το `base_url` σε `https://<username>.github.io/news-digest` (ή το domain σου) και το `name`.
5. **Πρώτη εκτέλεση**: Actions → *Daily brief* → **Run workflow**. Σε ~2 λεπτά το site είναι live.

Από εκεί και πέρα τρέχει μόνο του κάθε μέρα.

## Ρυθμίσεις

| Τι | Πού |
|---|---|
| Πηγές / ενότητες / πλήθος ειδήσεων | `feeds.yaml` |
| Όνομα, URL, newsletter, χορηγός, AdSense, analytics | `site.yaml` |
| Ώρα εκτέλεσης | `.github/workflows/daily.yml` → `cron` (σε UTC) |
| Μοντέλο AI | Repository variables `GITHUB_MODEL` (default `openai/gpt-4o`) ή `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`) |
| Κανόνες ουδετερότητας | `scripts/digest.py` → `NEUTRALITY_RULES` |
| Εμφάνιση | `templates/`, `static/style.css` |

Αλλαγές σε templates/CSS/site.yaml κάνουν αυτόματα rebuild χωρίς να ξαναγράφεται το digest.

Feeds που αποτυγχάνουν απλώς παραλείπονται· τα βλέπεις στο log του βήματος *Fetch & write digest*. Έλεγξε τα ελληνικά/βουλγαρικά URLs στην πρώτη εκτέλεση — τα Google News feeds υπάρχουν ως δίχτυ ασφαλείας και δίνουν και ποικιλία εκδοτών.

## Έσοδα — με σειρά απόδοσης

1. **Newsletter (το βασικό)**. Ένα digest αξίζει κυρίως ως email: οι συνδρομητές είναι δικοί σου και πουλιούνται σε χορηγούς.
   - Φτιάξε λογαριασμό στο Buttondown, βάλε το URL της φόρμας στο `newsletter_action`.
   - Secret `BUTTONDOWN_API_KEY` → κάθε πρωί, αφού ανέβει το site, φεύγει αυτόματα το email.
   - Variable `NEWSLETTER_LANG` = `el` ή `en`.
2. **Χορηγός ημέρας/εβδομάδας** (`sponsor` στο `site.yaml`): εμφανίζεται στο site *και* στο email. Το κοινό security/IT είναι από τα πιο ακριβά niches για χορηγίες — ένα πλαίσιο με vendor εργαλείων ή training πιάνει πολύ περισσότερα από display ads. Μπορεί να φιλοξενήσει και δικές σου υπηρεσίες.
3. **AdSense** (`adsense_client`): θέση ανάμεσα στις ενότητες + αυτόματο `ads.txt`. Θα χρειαστεί λίγες εβδομάδες περιεχομένου και σελίδα «Σχετικά» με email επικοινωνίας (υπάρχει ήδη). Σημείωση: η Google είναι αυστηρή με αυτόματα παραγόμενο περιεχόμενο, οπότε μη βασιστείς μόνο σε αυτό.
4. **Δωρεές** (`donate_url`): Ko-fi / GitHub Sponsors στο footer.

> **Πριν βάλεις διαφημίσεις**: οι όροι του GitHub Pages δεν επιτρέπουν site που είναι κυρίως εμπορικό. Για AdSense/χορηγίες μετάφερε το `site/` σε **Cloudflare Pages** (δωρεάν, ίδιο workflow — αλλάζεις μόνο το deploy βήμα) με δικό σου domain. Το δικό σου domain βοηθά έτσι κι αλλιώς και στο SEO και στην εμπιστοσύνη χορηγών.

**Ανάπτυξη κοινού**: το site έχει ήδη sitemap, canonical/hreflang για EL/EN, schema.org `NewsArticle`, OpenGraph και RSS ανά γλώσσα. Δήλωσέ το στο Google Search Console και στο Bing Webmaster Tools, και μοιράζου το «Με μια ματιά» κάθε μέρα σε LinkedIn/X/Telegram με link πίσω.

## Νομικά / δεοντολογία

_Δεν αποτελεί νομική συμβουλή — για εμπορική λειτουργία αξίζει μια σύντομη συμβουλή δικηγόρου._

Τι κάνει ήδη το site για να είναι «καθαρό»:

- **Μόνο άμεσα feeds εκδοτών.** Όχι Google News ή άλλους aggregators — οι όροι τους απαγορεύουν εμπορική χρήση. Μην τα ξαναπροσθέσεις στο `feeds.yaml`.
- **Δικά του κείμενα.** Γεγονότα με δικά του λόγια + link στην πηγή. Ο έλεγχος πρωτοτυπίας στο `digest.py` ξαναγράφει ό,τι μοιάζει με τη διατύπωση πηγής (κοινή σειρά 4 λέξεων ή >55% ομοιότητα).
- **Σήμανση AI** (AI Act, άρθρο 50): εμφανές badge κάτω από την ημερομηνία, σημείωση σε footer και email.
- **Διορθώσεις:** «Αναφορά λάθους» σε κάθε είδηση (με συμπληρωμένο `contact_email`) και σελίδα όρων με διαδικασία διόρθωσης/αφαίρεσης.
- **Ισορροπία πηγών:** εκδότες από διαφορετικούς χώρους + round-robin ανά εκδότη, ώστε κανένας να μην κυριαρχεί.

Τι κάνεις εσύ πριν από έσοδα:

1. Συμπλήρωσε `contact_email` και απάντα στις αναφορές λάθους.
2. Διάβασε τους όρους χρήσης RSS των κύριων πηγών σου· αν κάποιος εκδότης απαγορεύει ρητά εμπορική χρήση, αφαίρεσέ τον.
3. AdSense μόνο με το παράθυρο συναίνεσης της Google ενεργό (βλ. σχόλιο στο `site.yaml`).
4. Μετέφερε σε Cloudflare Pages + δικό σου domain (όροι GitHub Pages).
5. Δήλωσε τα έσοδα φορολογικά.

## Τοπικά

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...      # προαιρετικό
python scripts/fetch.py
python scripts/digest.py
BASE_URL=http://localhost:8000 python scripts/build.py
python -m http.server -d site 8000
```
